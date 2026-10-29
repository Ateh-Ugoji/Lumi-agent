"""Validation tests for the niche-extraction schemas (app/schemas/niche.py)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.niche import (
    CommentSample,
    GeoEvidenceItem,
    GeoProfile,
    GeoSignal,
    NicheConfig,
    NicheLLMOutput,
    NicheProfile,
    NicheQuery,
    PeerCandidate,
    RetweetContext,
    ScoredKeyword,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _geo(relevance: str = "global") -> GeoProfile:
    return GeoProfile(geo_relevance=relevance, geo_relevance_reason="test")


def _query(uses_geo: bool = False, tier: str = "core") -> NicheQuery:
    return NicheQuery(tier=tier, query_text="q", rationale="r", uses_geo=uses_geo)


def _llm_output(**overrides) -> NicheLLMOutput:
    base = {
        "primary_niche": "AI tools for African social media",
        "niche_slug": "ai-tools-african-social",
        "creator_role": "founder",
        "audience_description": "social media managers",
        "keywords": [],
        "geo": _geo(),
        "queries": [_query()],
        "confidence": 0.7,
    }
    base.update(overrides)
    return NicheLLMOutput(**base)


def test_local_first_requires_geo_query():
    with pytest.raises(ValidationError):
        _llm_output(geo=_geo("local_first"), queries=[_query(uses_geo=False)])
    ok = _llm_output(
        geo=_geo("local_first"),
        queries=[_query(uses_geo=True, tier="geo")],
    )
    assert ok.geo.geo_relevance == "local_first"


def test_global_relevance_needs_no_geo_query():
    assert _llm_output().geo.geo_relevance == "global"


def test_query_validation_fields_default_to_unvalidated():
    q = _query()
    assert q.validation_hits is None      # not 0 — unvalidated is not "zero hits"
    assert q.weak is False


def test_hour_histogram_must_be_24():
    from app.schemas.niche import DeterministicFeatures

    with pytest.raises(ValidationError):
        DeterministicFeatures(
            n_originals=1, n_replies=0, n_retweets=0, n_quotes=0,
            n_comments_received=0, thin_history=False,
            top_ngrams=[], top_hashtags=[], top_cashtags=[], top_mentions=[],
            top_reply_targets=[], top_retweet_authors=[], top_quote_authors=[],
            top_commenters=[], top_domains=[],
            lang_distribution={"en": 1.0},
            posting_hour_histogram_utc=[0] * 23,
        )


def test_scored_keyword_weight_bounds():
    with pytest.raises(ValidationError):
        ScoredKeyword(
            term="t", type="topic", weight=1.2,
            evidence={}, search_worthy=True,
        )


def test_geo_signal_requires_evidence():
    with pytest.raises(ValidationError):
        GeoSignal(
            scope="creator", level="country", value="NG",
            confidence=0.8, evidence=[],
        )
    ok = GeoSignal(
        scope="creator", level="country", value="NG", confidence=0.8,
        evidence=[GeoEvidenceItem(source="bio", detail='bio says "Lagos"')],
    )
    assert ok.evidence


def test_peer_candidate_defaults_never_guess_geo():
    c = PeerCandidate(handle="x", discovery_sources=["reply_target"])
    assert c.status == "candidate"         # not auto-promoted
    assert c.geo_match is None             # unknown, never guessed True
    assert c.niche_fit is None
    assert c.last_verified is None


def test_comment_sample_defaults():
    c = CommentSample(
        comment_post_id="1", on_post_id="2", on_post_owner="self",
        author_handle="a", text="nice", created_at=NOW,
    )
    assert c.looks_spam is False and c.is_owner_reply is False
    assert c.sampled_at is None


def test_retweet_context_carries_original():
    r = RetweetContext(retweet_post_id="1", original_author_handle="peer",
                       original_text="full text", published_at=NOW)
    assert r.original_author_handle == "peer"


def test_niche_profile_failed_status_constructs_without_fabrication():
    p = NicheProfile(
        profile_id=2, version=1, extracted_at=NOW, status="failed",
        niche_key=":global", primary_niche="", niche_slug="",
        secondary_niches=[], creator_role="", audience_description="",
        audience_roles=[], keywords=[], geo=_geo(), queries=[],
        peer_seeds=[], confidence=0.0, needs_user_confirmation=["niche"],
    )
    assert p.status == "failed" and p.keywords == []


def test_config_bands_and_weights():
    # contiguous peer bands: peer tops out where aspirational begins
    assert NicheConfig.PEER_BAND[1] == NicheConfig.ASPIRATIONAL_BAND[0]
    assert NicheConfig.ASPIRATIONAL_BAND[1] < 1e9
    # bio is the strongest signal, retweet weakest-but-one
    w = NicheConfig.SOURCE_WEIGHTS
    assert w["bio"] == max(w.values())
    assert w["retweet"] < w["reply"] < w["original"] < w["bio"]
    # hard-reject thresholds exist
    assert 0 < NicheConfig.MIN_ORIGINAL_RATIO < 1
    assert NicheConfig.BOT_SCORE_REJECT > 0.5
    assert NicheConfig.PEER_COMMENT_MINING is False
