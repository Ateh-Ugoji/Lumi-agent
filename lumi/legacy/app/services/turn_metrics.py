"""Read-only turn-latency metrics for `/health` (PROMPT 5 item 8).

`/health` must never fail because of this: any DB problem (or simply no
classified turns yet) yields an empty dict and the latency block is omitted
from the payload — missing metrics stay absent, never 0.
"""

import math

from sqlalchemy import select

from app.database import session_scope
from app.models.turn_classification import TurnClassification

SAMPLE_SIZE = 100  # last-N turns, newest first


def _nearest_rank(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile over an already-sorted, non-empty list."""
    index = max(0, math.ceil(q * len(sorted_values)) - 1)
    return sorted_values[min(index, len(sorted_values) - 1)]


async def recent_turn_latency(sample: int = SAMPLE_SIZE) -> dict:
    """p50/p95 of `timings.total_ms` over the newest classified turns.

    Returns `{}` when there is nothing to report (no rows, no `total_ms` key)
    or on ANY failure — a healthcheck degrades, it never 500s.
    """
    try:
        async with session_scope() as session:
            rows = (
                (
                    await session.execute(
                        select(TurnClassification.timings)
                        .order_by(TurnClassification.created_at.desc())
                        .limit(sample)
                    )
                )
                .scalars()
                .all()
            )
    except Exception:  # noqa: BLE001 - healthcheck must degrade, not fail
        return {}

    totals: list[float] = []
    for timings in rows:
        if not isinstance(timings, dict):
            continue
        value = timings.get("total_ms")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            totals.append(float(value))
    if not totals:
        return {}
    totals.sort()
    return {
        "turns_sampled": len(totals),
        "p50_ms": round(_nearest_rank(totals, 0.50), 1),
        "p95_ms": round(_nearest_rank(totals, 0.95), 1),
    }
