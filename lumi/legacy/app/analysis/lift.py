"""Lift-table builder — shared by the PEER pipeline and the user's own posts.

Same math both sides: winner_share = share of winners carrying a value,
baseline_share = share of the baseline carrying it, lift = winner_share /
baseline_share. Patterns need n >= MIN_N_FOR_LIFT on BOTH sides to be
"reported"; below that the row exists but is marked insufficient_data
(profile_extract_fixes.md Step 3: "Report only patterns with n >= 3").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.peer import LiftRow, PeerConfig

LIFT_DIMENSIONS: tuple[str, ...] = (
    "primary_framework",
    "hook_type",
    "format",
    "cta_type",
    "funnel_stage",
    "content_pillar",
    "hook_modality",
)


@dataclass
class LiftItem:
    """One post's dimension attributes + winner status for lift math."""

    attributes: dict[str, str] = field(default_factory=dict)
    is_winner: bool = False
    outlier_views: float = 1.0


def build_lift_table(
    items: list[LiftItem],
    *,
    min_n: int = PeerConfig.MIN_N_FOR_LIFT,
) -> list[LiftRow]:
    """Lift rows per (dimension, value), sorted by lift desc within a dimension."""
    winners = [i for i in items if i.is_winner]
    baseline = [i for i in items if not i.is_winner]
    n_winners = len(winners)
    n_baseline = len(baseline)

    rows: list[LiftRow] = []
    for dimension in LIFT_DIMENSIONS:
        values = sorted({i.attributes[dimension] for i in items if dimension in i.attributes})
        dim_rows: list[LiftRow] = []
        for value in values:
            w = [i for i in winners if i.attributes.get(dimension) == value]
            b = [i for i in baseline if i.attributes.get(dimension) == value]
            winner_share = len(w) / n_winners if n_winners else 0.0
            baseline_share = len(b) / n_baseline if n_baseline else 0.0
            lift = winner_share / baseline_share if baseline_share > 0 else None
            with_value = w + b
            avg_outlier = (
                sum(i.outlier_views for i in with_value) / len(with_value) if with_value else None
            )
            dim_rows.append(
                LiftRow(
                    dimension=dimension,
                    value=value,
                    n_winners=len(w),
                    n_baseline=len(b),
                    winner_share=round(winner_share, 4),
                    baseline_share=round(baseline_share, 4),
                    lift=round(lift, 4) if lift is not None else None,
                    avg_outlier_views=round(avg_outlier, 3) if avg_outlier is not None else None,
                    status="reported" if len(w) >= min_n and len(b) >= min_n else "insufficient_data",
                )
            )
        dim_rows.sort(
            key=lambda r: (r.lift is None, -(r.lift or 0.0), -r.n_winners, r.value)
        )
        rows.extend(dim_rows)
    return rows
