"""Read-only report over `turn_classifications` (L13 item 9 / PROMPT 5 item 1c).

Run: `uv run python scripts/classifier_report.py` (or with a limit: `... 200`).

Prints, for tuning the rules from real traffic (nothing here updates itself):
- class counts (rule class vs final class) and the `other` rate
- rate of Jev-vs-rule disagreement
- average Jev confidence by class
- Jev timeouts/errors
- top misrouted messages (rows a later user correction flagged)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import session_scope
from app.models.turn_classification import TurnClassification

DEFAULT_LIMIT = 500  # newest N rows to analyze
PREVIEW_LEN = 90


def _pct(part: int, whole: int) -> str:
    return f"{(100.0 * part / whole):.1f}%" if whole else "-"


async def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LIMIT
    async with session_scope() as session:
        rows = list(
            (
                await session.exec(
                    select(TurnClassification)
                    .order_by(TurnClassification.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )

    if not rows:
        print(f"no turn_classifications rows (last {limit})")
        return

    n = len(rows)
    rule_counts: dict[str, int] = {}
    final_counts: dict[str, int] = {}
    conf_by_class: dict[str, list[float]] = {}
    disagreement = 0
    jev_compared = 0
    jev_called = 0
    jev_errors: dict[str, int] = {}
    latencies: list[float] = []
    misroutes: list[TurnClassification] = []

    for row in rows:
        rule_counts[row.rule_class] = rule_counts.get(row.rule_class, 0) + 1
        final_counts[row.final_class] = final_counts.get(row.final_class, 0) + 1
        if row.jev_called:
            jev_called += 1
        if row.jev_class and row.rule_class:
            jev_compared += 1
            if row.jev_class != row.rule_class:
                disagreement += 1
        if row.jev_confidence is not None:
            conf_by_class.setdefault(row.final_class, []).append(row.jev_confidence)
        if row.jev_error:
            key = "timeout" if "time" in row.jev_error.lower() else row.jev_error
            jev_errors[key] = jev_errors.get(key, 0) + 1
        if row.total_latency_ms is not None:
            latencies.append(float(row.total_latency_ms))
        if row.user_corrected:
            misroutes.append(row)

    print(f"== classifier report: last {n} turns ==")
    print("  class counts (final_class):")
    for cls, count in sorted(final_counts.items(), key=lambda kv: -kv[1]):
        print(f"    {cls:<14} {count:>5}  ({_pct(count, n)})")
    other = final_counts.get("other", 0)
    print(f"  other rate: {other}/{n} = {_pct(other, n)}")

    print("  rule classes (what the rules matched first):")
    for cls, count in sorted(rule_counts.items(), key=lambda kv: -kv[1]):
        print(f"    {cls:<14} {count:>5}  ({_pct(count, n)})")

    print(f"  jev called on {jev_called}/{n} turns ({_pct(jev_called, n)})")
    if jev_compared:
        print(
            f"  jev-vs-rule disagreement: {disagreement}/{jev_compared} = "
            f"{_pct(disagreement, jev_compared)}"
        )
    else:
        print("  jev-vs-rule disagreement: no comparable rows")

    print("  average jev confidence by final class:")
    seen = False
    for cls, vals in sorted(conf_by_class.items()):
        seen = True
        print(f"    {cls:<14} {sum(vals) / len(vals):.3f}  (n={len(vals)})")
    if not seen:
        print("    (no confidence values recorded)")

    if jev_errors:
        print("  jev errors:")
        for err, count in sorted(jev_errors.items(), key=lambda kv: -kv[1]):
            print(f"    {err:<40} {count}")
    else:
        print("  jev errors: none")

    if latencies:
        latencies.sort()
        p50 = latencies[max(0, (len(latencies) + 1) // 2 - 1)]
        print(f"  turn latency: p50 {p50:.0f} ms over {len(latencies)} timed rows")

    print(f"  misrouted (user_corrected): {len(misroutes)}")
    for row in misroutes[:10]:
        preview = row.message_preview.replace("\n", " ")[:PREVIEW_LEN]
        print(
            f"    {row.rule_class} -> {row.final_class} (jev={row.jev_class}) "
            f": {preview}"
        )


if __name__ == "__main__":
    asyncio.run(main())
