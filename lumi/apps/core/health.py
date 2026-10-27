"""GET /health: database reachability and migration state."""

from __future__ import annotations

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse

VERSION = "0.1.0"


def health(request):
    checks: dict[str, str] = {}
    ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"
        ok = False
    if checks["database"] == "ok":
        try:
            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
            checks["migrations"] = (
                "ok" if not pending else f"pendientes: {len(pending)}"
            )
            ok = ok and not pending
        except Exception as exc:  # noqa: BLE001
            checks["migrations"] = f"error: {type(exc).__name__}"
            ok = False
    body = {"status": "ok" if ok else "degraded", "version": VERSION, "checks": checks}
    return JsonResponse(body, status=200 if ok else 503)
