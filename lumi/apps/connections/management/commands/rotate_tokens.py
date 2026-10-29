"""Re-encrypt every stored secret under the current ``TOKEN_ENCRYPTION_KEY``.

Rotation without downtime: set the new key, move the old one to ``TOKEN_ENCRYPTION_KEY_PREVIOUS``,
run this command, then drop ``_PREVIOUS``. Values are never decrypted into a model and never
printed: the command works on the ciphertext in the table and reports counts and row ids only.

A value that no configured key opens is left alone and listed, so the old key can be found again
before it is dropped. Each update checks the old ciphertext, so a row a request changed meanwhile
is skipped and picked up by the next run.
"""

from __future__ import annotations

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.core.fields import (
    EncryptedTextField,
    TokenDecryptError,
    needs_rotation,
    rotate_value,
)

BATCH = 500


def encrypted_columns() -> list[tuple[str, str, str, str]]:
    """``(label, table, pk column, column)`` for every encrypted field of every model."""
    found = []
    for model in apps.get_models():
        pk = model._meta.pk.column
        for field in model._meta.concrete_fields:
            if isinstance(field, EncryptedTextField):
                label = f"{model._meta.label}.{field.name}"
                found.append((label, model._meta.db_table, pk, field.column))
    return sorted(found)


def rotate_column(
    table: str, pk: str, column: str, *, dry_run: bool
) -> tuple[dict[str, int], list]:
    counts = {"rotated": 0, "current": 0, "unreadable": 0, "skipped": 0}
    bad_ids: list = []
    last = None
    quote = connection.ops.quote_name
    t, p, c = quote(table), quote(pk), quote(column)
    while True:
        where = f"AND {p} > %s" if last is not None else ""
        args = [last] if last is not None else []
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {p}, {c} FROM {t} WHERE {c} IS NOT NULL AND {c} <> '' {where} "
                f"ORDER BY {p} LIMIT {BATCH}",
                args,
            )
            rows = cursor.fetchall()
        if not rows:
            return counts, bad_ids
        for row_id, ciphertext in rows:
            last = row_id
            try:
                if not needs_rotation(ciphertext):
                    counts["current"] += 1
                    continue
                fresh = rotate_value(ciphertext)
            except TokenDecryptError:
                counts["unreadable"] += 1
                bad_ids.append(row_id)
                continue
            if dry_run:
                counts["rotated"] += 1
                continue
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {t} SET {c} = %s WHERE {p} = %s AND {c} = %s",
                    [fresh, row_id, ciphertext],
                )
                counts["rotated" if cursor.rowcount else "skipped"] += 1


class Command(BaseCommand):
    help = "Re-encrypt stored tokens under the current key. Prints counts and ids, never values."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count what would change; write nothing.",
        )

    def handle(self, *args, dry_run: bool = False, **options):
        totals = {"rotated": 0, "current": 0, "unreadable": 0, "skipped": 0}
        for label, table, pk, column in encrypted_columns():
            counts, bad_ids = rotate_column(table, pk, column, dry_run=dry_run)
            for key, n in counts.items():
                totals[key] += n
            line = ", ".join(f"{k}={v}" for k, v in counts.items())
            self.stdout.write(f"{label}: {line}")
            if bad_ids:
                shown = ", ".join(str(i) for i in bad_ids[:20])
                more = " ..." if len(bad_ids) > 20 else ""
                self.stdout.write(f"  unreadable ids: {shown}{more}")
        mode = "dry run, nothing written" if dry_run else "done"
        self.stdout.write(f"rotate_tokens ({mode}): {totals}")
        if totals["unreadable"]:
            raise CommandError(
                f"{totals['unreadable']} value(s) no configured key opens. "
                "Put the old key back in TOKEN_ENCRYPTION_KEY_PREVIOUS and run again."
            )
