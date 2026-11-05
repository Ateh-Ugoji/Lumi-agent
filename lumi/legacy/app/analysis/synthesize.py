"""Synthesis from lift rows only (Prompt 1 — the `synthesize` stage).

Every claim traces back to a lift row: a framework is reported only when it
appeared among winners materially more often than in that accounts' baseline
posts, pillars are reported `content_pillar` rows, whitespace is lift with
almost no baseline presence. Thin data yields fewer frameworks — possibly none —
plus warnings; nothing is ever invented to fill a report.

The narrative fields (`hook_formula`, `when_to_use`) are derived from the same
rows, so a report stays meaningful with no LLM call at all. An LLM polish pass
can be layered on later (Prompt 3) without changing this contract.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.analysis.winners import WinnerSelection
from app.schemas.peer import (
    AccountBaseline,
    LiftRow,
    NicheFrameworkReport,
    PeerConfig,
    PostTagging,
    SynthesisOutput,
    WinningFramework,
)

# A pattern must win at least this much more often than it appears in the
# baseline before it is called winning, and appear in almost no baseline posts
# to count as whitespace.
MIN_LIFT_FOR_FRAMEWORK = 1.5
WHITESPACE_MIN_LIFT = 1.5
WHITESPACE_MAX_BASELINE_SHARE = 0.2
MIN_PILLAR_LIFT = 1.0
MAX_FRAMEWORKS = 5
MAX_PILLARS = 5
MAX_WHITESPACE = 5

STRUCTURE_BY_FRAMEWORK: dict[str, list[str]] = {
    "pas": ["Problem", "Agitate", "Solution"],
    "aida": ["Attention", "Interest", "Desire", "Action"],
    "story_arc": ["Hook", "Context", "Turn", "Lesson"],
    "listicle": ["Promise", "List items", "Takeaway"],
    "tutorial": ["Goal", "Steps", "Result"],
    "bab": ["Before", "After", "Bridge"],
    "myth_bust": ["Myth", "Evidence", "Correction"],
    "hot_take": ["Contrarian claim", "Reasoning", "Proof"],
    "build_in_public": ["Context", "What shipped", "Proof"],
    "observation": ["Observation", "Implication"],
    "other": ["Hook", "Body"],
}


def _reported(rows: list[LiftRow], dimension: str) -> list[LiftRow]:
    return [
        r
        for r in rows
        if r.dimension == dimension and r.status == "reported" and r.lift is not None
    ]


def build_synthesis(
    lift_rows: list[LiftRow],
    taggings: list[PostTagging],
    winner_post_ids: list[str],
) -> SynthesisOutput:
    """Frameworks, pillars and whitespace — all derived from reported lift rows."""
    warnings: list[str] = []
    winners = set(winner_post_ids)
    tagged = {
        t.post_id: t
        for t in taggings
        if t.status == "ok" and t.analysis is not None and t.post_id in winners
    }

    framework_rows = sorted(
        (r for r in _reported(lift_rows, "primary_framework") if r.lift >= MIN_LIFT_FOR_FRAMEWORK),
        key=lambda r: (-(r.lift or 0.0), -r.n_winners),
    )
    hook_rows = {r.value: r for r in _reported(lift_rows, "hook_type")}

    frameworks: list[WinningFramework] = []
    for row in framework_rows[:MAX_FRAMEWORKS]:
        matching = [t for t in tagged.values() if t.analysis and t.analysis.body.primary_framework == row.value]
        evidence = [t.post_id for t in matching]
        dominant_hook = max(
            {t.analysis.hook.hook_type for t in matching if t.analysis},
            key=lambda h: sum(1 for t in matching if t.analysis and t.analysis.hook.hook_type == h),
            default="other",
        )
        structure = STRUCTURE_BY_FRAMEWORK.get(row.value, STRUCTURE_BY_FRAMEWORK["other"])
        confidences = [t.analysis.body.framework_confidence for t in matching if t.analysis]
        confidence = round(sum(confidences) / len(confidences), 2) if confidences else PeerConfig.LOW_CONFIDENCE

        supporting = [f"{row.dimension}={row.value}"]
        if dominant_hook in hook_rows:
            supporting.append(f"hook_type={dominant_hook}")

        frameworks.append(
            WinningFramework(
                name=row.value.replace("_", " ").title(),
                structure=structure,
                hook_formula=f"[{dominant_hook.replace('_', ' ')}] hook -> {' -> '.join(structure)}",
                when_to_use=(
                    f"when a {row.value.replace('_', ' ')} post can beat this account's own median "
                    f"(lift {row.lift}x vs baseline, {row.n_winners} of {row.n_winners + row.n_baseline} posts)"
                ),
                evidence_post_ids=evidence,
                supporting_lift_rows=supporting,
                confidence=max(0.0, min(1.0, confidence)),
            )
        )

    pillars = [
        r.value
        for r in sorted(
            (r for r in _reported(lift_rows, "content_pillar") if r.lift >= MIN_PILLAR_LIFT),
            key=lambda r: -(r.lift or 0.0),
        )[:MAX_PILLARS]
    ]

    whitespace = [
        f"{r.dimension}={r.value}"
        for r in sorted(
            (
                r
                for r in lift_rows
                if r.status == "reported"
                and r.lift is not None
                and r.lift >= WHITESPACE_MIN_LIFT
                and r.baseline_share <= WHITESPACE_MAX_BASELINE_SHARE
            ),
            key=lambda r: -(r.lift or 0.0),
        )[:MAX_WHITESPACE]
    ]

    if not frameworks:
        warnings.append(
            f"no framework pattern lifted >= {MIN_LIFT_FOR_FRAMEWORK}x with enough posts on both "
            "sides — the report names no frameworks rather than guessing"
        )
    if not tagged:
        warnings.append("no winner carried a successful blind tagging — lift rows are uninformative")

    return SynthesisOutput(
        winning_frameworks=frameworks,
        content_pillars=pillars,
        whitespace=whitespace,
        warnings=warnings,
    )


def build_report(
    *,
    niche: str,
    accounts: list[AccountBaseline],
    selection: WinnerSelection,
    taggings: list[PostTagging],
    lift_rows: list[LiftRow],
    now: datetime | None = None,
) -> NicheFrameworkReport:
    """Assemble the final report with an honest status.

    `insufficient_data` when winner selection came up short; `failed` when the
    blind tagging produced nothing usable. In both cases `synthesis` is None and
    no frameworks are attached — a failed report carries no fabricated content.
    """
    now = now or datetime.now(UTC)
    winner_post_ids = [w.post_id for w in selection.winners]
    tagged_ok = [t for t in taggings if t.status == "ok" and t.analysis is not None]

    if selection.status == "insufficient_data":
        status = "insufficient_data"
        synthesis: SynthesisOutput | None = None
    elif not tagged_ok:
        status = "failed"
        synthesis = None
    else:
        status = "ok"
        synthesis = build_synthesis(lift_rows, taggings, winner_post_ids)

    return NicheFrameworkReport(
        niche=niche,
        generated_at=now,
        status=status,  # type: ignore[arg-type]
        accounts=accounts,
        winner_post_ids=winner_post_ids,
        posts_analyzed=len(tagged_ok),
        lift_table=lift_rows,
        synthesis=synthesis,
    )
