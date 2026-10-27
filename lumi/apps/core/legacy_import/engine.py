"""Importer registry, run context, report and verification.

Each app that owns legacy tables adds ``apps/<app>/legacy_import.py`` and calls
:func:`register` at import time. The command discovers those modules, so ARCHITECT does not
import code owned by other teams.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

from django.apps import apps as django_apps
from django.db import connection, models, transaction

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
    ) -> None:
        self.legacy = legacy
        self.user = user
        self.memory_md = memory_md
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
        self, source_table: str, source_pk: Any, target_table: str, target_pk: int
    ) -> None:
        pk = str(source_pk)
        self.mapped(source_table, target_table)[pk] = target_pk
        self._pending.append(
            LegacyImportMap(
                source_table=source_table,
                source_pk=pk,
                target_table=target_table,
                target_pk=target_pk,
            )
        )

    def skip(self, source_table: str, source_pk: Any, reason: str) -> None:
        self.remember(source_table, source_pk, SKIPPED, 0)
        self.table(source_table).skipped += 1
        self.warn(f"{source_table} {source_pk}: {reason}")

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
) -> Report:
    """Import ``path`` in one transaction (one savepoint per importer).

    A failure in any importer rolls back everything, so a half-imported database is not
    possible. ``dry_run`` runs the same code and rolls back at the end.
    """
    chosen = importers()
    legacy = LegacyDb(path)
    try:
        with transaction.atomic():
            ctx = ImportContext(legacy, _ensure_user(user_email), memory_md=memory_md)
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

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def verify_import(path: str) -> list[VerifyRow]:
    """Compare the row count of each legacy table with the rows the id map accounts for."""
    covered = {t for imp in importers() for t in imp.tables}
    legacy = LegacyDb(path)
    try:
        counts = {t: legacy.count(t) for t in LEGACY_TABLES}
    finally:
        legacy.close()
    accounted: Counter[str] = Counter()
    pairs = (
        LegacyImportMap.objects.filter(source_table__in=LEGACY_TABLES)
        .values_list("source_table", "source_pk")
        .distinct()
    )
    for table, _ in pairs:
        accounted[table] += 1
    rows = []
    for table in LEGACY_TABLES:
        n, got = counts[table], accounted[table]
        if n == got:
            status = "ok"
        elif table not in covered:
            status = "sin importador"
        else:
            status = "difiere"
        rows.append(VerifyRow(table, n, got, status))
    return rows
