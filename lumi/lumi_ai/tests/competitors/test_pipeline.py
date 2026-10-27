"""The competitor pipeline against fake ports: honest statuses, cache, ordering, caps."""

from __future__ import annotations

import pytest

from lumi_ai.competitors.pipeline import PipelineDeps, run_peer_pipeline
from lumi_ai.config import AIConfig
from lumi_ai.ports import (
    BudgetExceeded,
    LiveDisabled,
    ProviderUnavailable,
    UnsupportedPlatform,
)
from lumi_ai.tests.competitors.support import (
    NOW,
    FakePeerStore,
    FakeReports,
    FakeSocial,
    TaggerLLM,
    make_posts,
)

HANDLES = ["alice", "bob", "carol"]


def _winner_ids(handles=HANDLES) -> list[str]:
    """Winners (0-4) and a few non-winners (5-9) use PAS, so the baseline has the pattern too."""
    return [f"{h}-{i}" for h in handles for i in range(10)]


def _rig(posts=None, errors=None, *, llm=None, config=None, indexed=None):
    reports = FakeReports()
    social = FakeSocial(
        posts if posts is not None else {h: make_posts(h, winners=5) for h in HANDLES},
        errors,
    )
    peers = FakePeerStore(reports)
    llm = llm or TaggerLLM(pas_ids=_winner_ids())
    deps = PipelineDeps(
        social=social,
        llm=llm,
        reports=reports,
        peer_posts=peers,
        config=config or AIConfig(),
        index_peer_posts=(indexed.extend if indexed is not None else None),
    )
    return deps, social, reports, peers, llm


async def _run(deps, handles=HANDLES, platform="x"):
    return await run_peer_pipeline(
        deps,
        profile_id=1,
        platform=platform,
        niche="ai tools",
        niche_key="ai-tools:global",
        handles=handles,
        now=NOW,
    )


async def test_full_run_saves_an_ok_report_with_frameworks_and_evidence() -> None:
    indexed: list = []
    deps, _, reports, peers, _ = _rig(indexed=indexed)
    result = await _run(deps)
    assert result.report.status == "ok"
    saved = reports.reports[0]
    assert saved.status == "ok" and saved.winner_count == 15
    assert saved.query == "ai tools" and saved.peers_analyzed == 3
    assert reports.last_in.peer_handles == {"x": ("alice", "bob", "carol")}
    assert saved.frameworks, "winners share a framework: it must be reported"
    for fw in saved.frameworks:
        assert fw.payload["key"] == fw.name and fw.payload["title"] == fw.title
        stored = {r.external_id for r in peers.rows.values()}
        assert fw.evidence_post_refs
        assert all(ref.split(":", 1)[1] in stored for ref in fw.evidence_post_refs)
    assert {p.external_id for p in indexed} == set(result.report.winner_post_ids)


async def test_peer_posts_are_stored_before_the_report() -> None:
    deps, _, reports, _, _ = _rig()
    await _run(deps)
    assert reports.order == ["peer_posts", "report"]


async def test_second_run_retags_nothing() -> None:
    deps, _, _, _, llm = _rig()
    await _run(deps)
    first = llm.calls
    assert first > 0
    again = await _run(deps)
    assert llm.calls == first
    assert again.report.status == "ok"


async def test_too_few_winners_is_insufficient_data_without_frameworks() -> None:
    flat = {h: make_posts(h, winners=0) for h in HANDLES}
    deps, _, reports, _, _ = _rig(flat)
    result = await _run(deps)
    saved = reports.reports[0]
    assert saved.status == "insufficient_data" and saved.frameworks == ()
    assert "thresholds were not lowered" in (saved.detail or "")
    assert result.report.synthesis is None


async def test_budget_exceeded_midway_keeps_what_was_read_and_warns() -> None:
    deps, _, reports, _, _ = _rig(errors={"carol": BudgetExceeded("spent 50/50")})
    result = await _run(deps)
    assert result.scanned.keys() == {"alice", "bob"}
    # two accounts still give 10 winners (>= 8): the report stands, and says it is partial
    assert reports.reports[0].status == "ok" and reports.reports[0].peers_analyzed == 2
    assert any("credit budget" in w for w in result.report.warnings)


async def test_budget_exceeded_on_the_first_account_is_insufficient_not_failed() -> (
    None
):
    deps, social, reports, _, llm = _rig(errors={"*": BudgetExceeded("0 left")})
    await _run(deps)
    assert reports.reports[0].status == "insufficient_data"
    assert llm.calls == 0 and len(social.calls) == 1


async def test_one_bad_account_does_not_sink_the_run() -> None:
    deps, _, reports, _, _ = _rig(errors={"bob": ProviderUnavailable("down")})
    result = await _run(deps)
    assert result.failures and result.failures[0].startswith("@bob")
    assert result.scanned.keys() == {"alice", "carol"}
    assert reports.reports[0].peers_analyzed == 2


@pytest.mark.parametrize("platform", ["linkedin", "facebook"])
async def test_unsupported_platform_is_a_failed_report_with_no_calls_after_the_first(
    platform,
) -> None:
    deps, social, reports, peers, llm = _rig(
        errors={"*": UnsupportedPlatform(f"no third-party posts on {platform}")}
    )
    result = await _run(deps, platform=platform)
    assert reports.reports[0].status == "failed"
    assert "provider refused" in (result.detail or "")
    assert len(social.calls) == 1 and llm.calls == 0 and not peers.rows


async def test_live_disabled_stops_the_run() -> None:
    deps, social, reports, _, _ = _rig(errors={"*": LiveDisabled("LIVE_SOCIAL_DATA=0")})
    await _run(deps)
    assert reports.reports[0].status == "failed" and len(social.calls) == 1


async def test_every_account_empty_is_failed() -> None:
    deps, _, reports, _, _ = _rig({h: [] for h in HANDLES})
    await _run(deps)
    assert reports.reports[0].status == "failed"
    assert "no account could be read" in (reports.reports[0].detail or "")


async def test_unusable_tagging_is_failed_and_carries_no_framework() -> None:
    deps, _, reports, _, _ = _rig(llm=TaggerLLM(broken=True))
    await _run(deps)
    saved = reports.reports[0]
    assert saved.status == "failed" and saved.frameworks == ()
    assert reports.tag_rows  # failures are recorded, never an analysis
    assert all(t.analysis is None for t in reports.tag_rows.values())


async def test_caps_limit_accounts_and_tagged_posts_and_keep_winners() -> None:
    cfg = AIConfig(peer_max_accounts=2, peer_max_posts_to_tag=12)
    deps, social, _, _, llm = _rig(config=cfg)
    result = await _run(deps)
    assert [c[1] for c in social.calls] == ["alice", "bob"]
    tagged = {i for batch in llm.batches for i in batch}
    assert len(tagged) == 12
    assert set(result.report.winner_post_ids) <= tagged  # winners are tagged first


async def test_handles_are_normalized_and_deduplicated() -> None:
    deps, social, _, _, _ = _rig()
    await _run(deps, handles=["@Alice", "alice", " ", "BOB"])
    assert [c[1] for c in social.calls] == ["alice", "bob"]
