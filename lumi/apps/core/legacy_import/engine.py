"""Importer registry, run context, report and verification.

Each app that owns legacy tables adds ``apps/<app>/legacy_import.py`` and calls
:func:`register` at import time. The command discovers those modules, so ARCHITECT does not
import code owned by other teams.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

from django.apps import apps as django_apps
from django.db import connection, models, transaction

from apps.core.choices import LegacyOutcome
from apps.core.legacy_import.reader import LegacyDb
from apps.core.models import LegacyImportMap

log = logging.getLogger(__name__)

IMPORTED_EMAIL = "importado@lumi.invalid"
SKIPPED = "(omitida)"  # target_table of a legacy row that was left out on purpose
MAX_WARNINGS = 200

LEGACY_TABLES: tuple[str, ...] = (
    "profiles",
    "profile_snapshots",
    "profile_baseline",
    "posts",
    "metric_snapshots",
    "user_activity",
    "listening_matches",
    "poll_config",
    "user_search_requests",
    "chat_messages",
    "turn_classifications",
    "voice_profiles",
    "style_answers",
    "own_post_analysis",
    "post_taggings",
    "peer_frameworks",
    "niche_framework_reports",
    "repurpose_requests",
    "repurpose_attempts",
    "user_actions",
    "mcp_auth_accounts",
)


class ImportConflict(Exception):
    """The target database already holds data the import cannot reconcile."""


@dataclass
class TableReport:
    read: int = 0
    imported: int = 0
    already: int = 0  # mapped by an earlier run
    merged: int = 0  # folded into an existing row (duplicates)
    skipped: int = 0  # left out on purpose, with a warning


@dataclass
class Report:
    tables: dict[str, TableReport] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    dropped_warnings: int = 0

    def lines(self) -> list[str]:
        out = []
        for name, t in self.tables.items():
            out.append(
                f"{name}: leídas {t.read}, importadas {t.imported}, ya importadas {t.already}, "
                f"fusionadas {t.merged}, omitidas {t.skipped}"
            )
        out.extend(f"aviso: {w}" for w in self.warnings)
        if self.dropped_warnings:
            out.append(f"aviso: {self.dropped_warnings} avisos más no se muestran")
        return out


@dataclass(frozen=True)
class Importer:
    """One unit of the import. ``order`` ranges: profiles 10-79, chat 80-99, INTELLIGENCE
    100-199, CONNECT 200-299."""

    name: str
    tables: tuple[str, ...]
    order: int
    run: Callable[[ImportContext], None]
    # Reads the legacy file and returns, per table, how many rows lost content ``--verify``
    # cannot see by counting rows (a column mapped into another table, for example).
    check: Callable[[LegacyDb], dict[str, int]] | None = None


_REGISTRY: dict[str, Importer] = {}


def register(importer: Importer) -> None:
    _REGISTRY[importer.name] = importer


def discover() -> None:
    """Import ``<app>.legacy_import`` of every installed app, when it exists."""
    for config in django_apps.get_app_configs():
        module = f"{config.name}.legacy_import"
        try:
            import_module(module)
        except ModuleNotFoundError as exc:
            if exc.name != module:
                raise


def importers() -> list[Importer]:
    discover()
    return sorted(_REGISTRY.values(), key=lambda i: (i.order, i.name))


class ImportContext:
    """Everything an importer needs: the legacy file, the user, the id map and the report."""

    def __init__(
        self,
        legacy: LegacyDb,
        user: Any,
        *,
        memory_md: str | None = None,
        handle_mappings: str | None = None,
    ) -> None:
        self.legacy = legacy
        self.user = user
        self.memory_md = memory_md
        self.handle_mappings = handle_mappings
        self.report = Report()
        self.cache: dict[str, Any] = {}
        self._maps: dict[tuple[str, str], dict[str, int]] = {}
        self._pending: list[LegacyImportMap] = []

    def table(self, name: str) -> TableReport:
        return self.report.tables.setdefault(name, TableReport())

    def warn(self, message: str) -> None:
        log.warning("import_legacy: %s", message)
        if len(self.report.warnings) < MAX_WARNINGS:
            self.report.warnings.append(message)
        else:
            self.report.dropped_warnings += 1

    def mapped(self, source_table: str, target_table: str) -> dict[str, int]:
        """``source_pk -> target_pk`` for one pair of tables (loaded once, kept current)."""
        key = (source_table, target_table)
        if key not in self._maps:
            self._maps[key] = {
                pk: target
                for pk, target in LegacyImportMap.objects.filter(
                    source_table=source_table, target_table=target_table
                ).values_list("source_pk", "target_pk")
            }
        return self._maps[key]

    def is_done(self, source_table: str, source_pk: Any, target_table: str) -> bool:
        pk = str(source_pk)
        return pk in self.mapped(source_table, target_table) or pk in self.mapped(
            source_table, SKIPPED
        )

    def remember(
        self,
        source_table: str,
        source_pk: Any,
        target_table: str,
        target_pk: int,
        *,
        outcome: str = LegacyOutcome.IMPORTED,
        row: dict[str, Any] | None = None,
    ) -> None:
        """Record where a legacy row went.

        Pass ``row`` whenever the new tables do not hold everything the row said (the
        database refuses a merged or skipped entry without it). ``row`` is stored as JSON,
        encrypted, so a discarded token never sits in plain text.
        """
        pk = str(source_pk)
        if outcome != LegacyOutcome.IMPORTED and row is None:
            raise ValueError(f"{source_table} {pk}: {outcome} needs the legacy row")
        self.mapped(source_table, target_table)[pk] = target_pk
        self._pending.append(
            LegacyImportMap(
                source_table=source_table,
                source_pk=pk,
                target_table=target_table,
                target_pk=target_pk,
                outcome=outcome,
                payload=None if row is None else _dump(row),
            )
        )

    def merge(
        self,
        source_table: str,
        row: dict[str, Any],
        target_table: str,
        target_pk: int,
        reason: str | None = None,
    ) -> None:
        """The row folded into ``target_pk``. Its full content stays in the map."""
        self.remember(
            source_table,
            row["id"],
            target_table,
            target_pk,
            outcome=LegacyOutcome.MERGED,
            row=row,
        )
        self.table(source_table).merged += 1
        if reason:
            self.warn(f"{source_table} {row['id']}: {reason}")

    def skip(self, source_table: str, row: dict[str, Any] | Any, reason: str) -> None:
        """Record a legacy row that cannot be imported, keeping the whole row.

        A bare legacy id is accepted (the old signature): the row is read back so the
        payload is never lost.
        """
        if not isinstance(row, dict):
            found = self.legacy.get(source_table, row)
            if found is None:
                raise ValueError(f"{source_table} {row}: the legacy row does not exist")
            row = found
        self.remember(
            source_table,
            row["id"],
            SKIPPED,
            0,
            outcome=LegacyOutcome.SKIPPED,
            row=row,
        )
        self.table(source_table).skipped += 1
        self.warn(f"{source_table} {row['id']}: {reason}")

    def flush(self) -> None:
        if self._pending:
            LegacyImportMap.objects.bulk_create(
                self._pending, batch_size=2000, ignore_conflicts=True
            )
            self._pending.clear()

    def require_free_ids(self, model: type[models.Model], ids: Iterable[int]) -> None:
        """Abort when a legacy id we want to keep is taken by a row that is not ours."""
        wanted = list(ids)
        for i in range(0, len(wanted), 5000):
            taken = list(
                model.objects.filter(pk__in=wanted[i : i + 5000]).values_list(
                    "pk", flat=True
                )[:5]
            )
            if taken:
                raise ImportConflict(
                    f"{model._meta.db_table}: el id {taken[0]} ya existe y no viene de "
                    "este origen. Importa sobre una base vacía o libera ese id."
                )


def _dump(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, default=str, sort_keys=True)


def sync_sequence(model: type[models.Model]) -> None:
    """Move the id sequence past the largest id so the next insert does not collide."""
    table = model._meta.db_table
    quoted = connection.ops.quote_name(table)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'),"
            f" GREATEST((SELECT COALESCE(MAX(id), 1) FROM {quoted}), 1))",
            [table],
        )


def _ensure_user(email: str | None):
    from apps.accounts.models import User

    address = (email or IMPORTED_EMAIL).strip().lower()
    user = User.objects.filter(email=address).first()
    return user or User.objects.create_user(address)


def run_import(
    path: str,
    *,
    user_email: str | None = None,
    dry_run: bool = False,
    memory_md: str | None = None,
    handle_mappings: str | None = None,
) -> Report:
    """Import ``path`` in one transaction (one savepoint per importer).

    A failure in any importer rolls back everything, so a half-imported database is not
    possible. ``dry_run`` runs the same code and rolls back at the end.
    """
    chosen = importers()
    legacy = LegacyDb(path)
    try:
        with transaction.atomic():
            ctx = ImportContext(
                legacy,
                _ensure_user(user_email),
                memory_md=memory_md,
                handle_mappings=handle_mappings,
            )
            for importer in chosen:
                with transaction.atomic():
                    importer.run(ctx)
                    ctx.flush()
            if dry_run:
                transaction.set_rollback(True)
    finally:
        legacy.close()
    return ctx.report


@dataclass(frozen=True)
class VerifyRow:
    table: str
    legacy: int
    accounted: int
    status: str  # "ok", "difiere" or "sin importador"
    imported: int = 0
    merged: int = 0
    skipped: int = 0
    without_payload: int = 0  # merged or skipped rows that lost their payload
    lost_content: int = (
        0  # rows whose mapped columns are in neither a table nor the payload
    )

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def verify_import(
    path: str,
    *,
    user_email: str | None = None,
    handle_mappings: str | None = None,
) -> list[VerifyRow]:
    """Prove that every legacy row is imported, merged or skipped, with its payload kept.

    A table is ``ok`` when the distinct legacy ids in the map equal the legacy row count and no
    merged or skipped row lacks its payload. ``merged`` and ``skipped`` rows count as accounted
    for: their content is in ``legacy_import_map.payload``.

    With ``handle_mappings`` (the legacy picks file) one more row is added for
    ``user_saved_handles``: it is ``difiere`` when a usable pick is missing for ``user_email``.
    """
    covered = {t for imp in importers() for t in imp.tables}
    legacy = LegacyDb(path)
    lost: Counter[str] = Counter()
    try:
        counts = {t: legacy.count(t) for t in LEGACY_TABLES}
        ids = {t: legacy.ids(t) for t in LEGACY_TABLES}
        for imp in importers():
            if imp.check is not None:
                lost.update(imp.check(legacy))
    finally:
        legacy.close()
    # One outcome per legacy row: the strongest wins (imported over merged over skipped).
    rank = {
        LegacyOutcome.IMPORTED: 0,
        LegacyOutcome.MERGED: 1,
        LegacyOutcome.SKIPPED: 2,
    }
    best: dict[str, dict[str, str]] = {t: {} for t in LEGACY_TABLES}
    bare: Counter[str] = Counter()
    for table, pk, outcome, has_payload in (
        LegacyImportMap.objects.filter(source_table__in=LEGACY_TABLES)
        .values_list(
            "source_table", "source_pk", "outcome", models.Q(payload__isnull=False)
        )
        .iterator()
    ):
        current = best[table].get(pk)
        if current is None or rank[outcome] < rank[current]:
            best[table][pk] = outcome
        if outcome != LegacyOutcome.IMPORTED and not has_payload:
            bare[table] += 1
    rows = []
    for table in LEGACY_TABLES:
        mine = best[table]
        n = counts[table]
        got = len(mine.keys() & ids[table])
        stray = len(mine.keys() - ids[table])
        kinds = Counter(mine.values())
        if n == got and not stray and not bare[table] and not lost[table]:
            status = "ok"
        elif table not in covered:
            status = "sin importador"
        else:
            status = "difiere"
        rows.append(
            VerifyRow(
                table,
                n,
                got,
                status,
                imported=kinds[LegacyOutcome.IMPORTED],
                merged=kinds[LegacyOutcome.MERGED],
                skipped=kinds[LegacyOutcome.SKIPPED],
                without_payload=bare[table],
                lost_content=lost[table],
            )
        )
    if handle_mappings:
        from apps.core.legacy_import.handle_mappings import verify_saved_handles

        rows.append(verify_saved_handles(handle_mappings, user_email))
    return rows
