"""Import of the legacy SQLite ``lumi.db`` (T8). See docs/CONTRATOS.md section 10."""

from apps.core.legacy_import import handle_mappings  # noqa: F401  (registers its importer)
from apps.core.legacy_import.engine import (
    LEGACY_TABLES,
    SKIPPED,
    ImportConflict,
    ImportContext,
    Importer,
    Report,
    TableReport,
    VerifyRow,
    register,
    run_import,
    verify_import,
)
from apps.core.legacy_import.reader import LegacyDb, to_bool, to_dt, to_json

__all__ = [
    "LEGACY_TABLES",
    "SKIPPED",
    "ImportConflict",
    "ImportContext",
    "Importer",
    "LegacyDb",
    "Report",
    "TableReport",
    "VerifyRow",
    "register",
    "run_import",
    "to_bool",
    "to_dt",
    "to_json",
    "verify_import",
]
