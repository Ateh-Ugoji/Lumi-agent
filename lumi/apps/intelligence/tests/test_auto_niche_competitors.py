from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import async_to_sync

from apps.connections.account_links import link_account
from apps.connections.accounts import sync_pfm_accounts
from apps.connections.models import AccountStatus, ConnectedAccount, PfmLink, Provider
from apps.core.models import BackgroundJob
from apps.intelligence.models import (
    NichePreference,
    NichePreferenceHandle,
    NichePreferenceKeyword,
    NicheSource,
)
from apps.intelligence.tasks import (
    BOOTSTRAP_KIND,
    _ensure_niche_and_competitors,
    _infer_niche,
)
from lumi_ai import ports
from lumi_ai.config import AIConfig


class DummyPost:
    def __init__(self, text: str):
        self.text = text
        self.caption = text


@pytest.mark.django_db
class TestNicheInference:
    @pytest.mark.asyncio
    async def test_infer_niche_heuristics_extracts_hashtags_and_keywords(self):
        wiring = SimpleNamespace(chain=None)
        posts = [
            DummyPost("Launching our new #AI agent tool! #automation #saas"),
            DummyPost("How #AI agents automate workflows for founders #automation"),
            DummyPost("Building autonomous tech products #saas #startups"),
        ]
        title, keywords = await _infer_niche(
            wiring,
            handle="atehofficial",
            display_name="Ateh",
            platform="x",
            posts=posts,
        )
        assert "Ai Content" in title or "Content" in title
        assert "ai" in keywords or "automation" in keywords or "saas" in keywords

    @pytest.mark.asyncio
    async def test_infer_niche_with_llm_chain(self):
        fake_llm_result = SimpleNamespace(
            completion=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"title": "Agentic AI & Automation", "keywords": ["ai agents", "automation", "llm systems"]}'
                        )
                    )
                ]
            )
        )
        chain_mock = SimpleNamespace(
            providers=["openlux"],
            complete=AsyncMock(return_value=fake_llm_result),
        )
        wiring = SimpleNamespace(chain=chain_mock)
        posts = [DummyPost("Latest breakthrough in AI reasoning agents")]

        title, keywords = await _infer_niche(
            wiring,
            handle="atehofficial",
            display_name="Ateh",
            platform="x",
            posts=posts,
        )
        assert title == "Agentic AI & Automation"
        assert keywords == ["ai agents", "automation", "llm systems"]


@pytest.mark.django_db
class TestCompetitorDiscoveryAndPersistence:
    def test_discovers_real_competitors_excluding_own_handle(self, owner, make_profile):
        profile = make_profile(owner, handle="atehofficial", platform="x")

        # Mock social search returning user's own handle and two competitor handles
        own_post = ports.PostIn(
            platform="x",
            external_id="post-own",
            text="My own post about AI",
            published_at=datetime.now(UTC),
            author_handle="atehofficial",
            metrics=ports.PostMetrics(likes=50),
        )
        peer1_post = ports.PostIn(
            platform="x",
            external_id="post-peer1",
            text="Competitor post 1 on AI agents",
            published_at=datetime.now(UTC),
            author_handle="competitor_one",
            metrics=ports.PostMetrics(likes=120),
        )
        peer2_post = ports.PostIn(
            platform="x",
            external_id="post-peer2",
            text="Competitor post 2 on workflows",
            published_at=datetime.now(UTC),
            author_handle="competitor_two",
            metrics=ports.PostMetrics(likes=90),
        )

        mock_social = SimpleNamespace(
            search_posts=AsyncMock(return_value=[own_post, peer1_post, peer2_post])
        )

        fake_saved_report = SimpleNamespace(id=999, status="ok", frameworks=[])
        fake_pipeline_result = SimpleNamespace(
            saved=fake_saved_report,
            report=SimpleNamespace(warnings=[]),
            scanned={},
            detail=None,
            failures={},
            video_analyzed=0,
            video_notes=[],
        )

        pipeline_deps = SimpleNamespace(
            social=mock_social,
            config=AIConfig(peer_discovery_posts=20, peer_max_accounts=5),
        )
        competitors = SimpleNamespace(
            pipeline=pipeline_deps,
            social=mock_social,
        )

        wiring = SimpleNamespace(
            competitors=competitors,
            chain=None,
            config=AIConfig(peer_discovery_posts=20, peer_max_accounts=5),
        )

        posts = [DummyPost("Building AI agents #automation")]

        with patch(
            "lumi_ai.competitors.pipeline.run_peer_pipeline",
            AsyncMock(return_value=fake_pipeline_result),
        ):
            res = async_to_sync(_ensure_niche_and_competitors)(wiring, profile.pk, posts)

        # 1. User's own handle (@atehofficial) MUST be excluded from competitors!
        assert "atehofficial" not in res["competitors"]
        assert "competitor_one" in res["competitors"]
        assert "competitor_two" in res["competitors"]

        # 2. Inferred NichePreference must exist in DB
        pref = NichePreference.objects.filter(profile_id=profile.pk, is_active=True).first()
        assert pref is not None
        assert pref.source == NicheSource.INFERRED
        assert NichePreferenceKeyword.objects.filter(preference=pref).count() > 0

        # 3. Discovered competitor handles must be saved to NichePreferenceHandle
        tracked = list(
            NichePreferenceHandle.objects.filter(preference=pref).values_list(
                "handle__handle_normalized", flat=True
            )
        )
        assert "competitor_one" in tracked
        assert "competitor_two" in tracked
        assert "atehofficial" not in tracked


@pytest.mark.django_db
class TestAutoTriggerOnAccountConnect:
    def test_sync_pfm_enqueues_bootstrap_job_for_new_profile(self, owner):
        PfmLink.objects.create(user=owner, external_id="lumi-mine")
        fake_acc = SimpleNamespace(
            id="pfm_acc_123",
            platform="x",
            username="atehofficial",
            status="connected",
            external_id="lumi-mine",
            profile_photo_url="https://example.com/avatar.jpg",
        )

        with patch("apps.connections.accounts._list_pfm_accounts", return_value=[fake_acc]):
            count = sync_pfm_accounts(owner)

        assert count == 1
        account = ConnectedAccount.objects.get(user=owner, external_account_id="pfm_acc_123")
        assert account.status == AccountStatus.ACTIVE
        assert account.social_profile_id is not None

        # Verify BOOTSTRAP_KIND job was enqueued in background_jobs
        job = BackgroundJob.objects.filter(
            user=owner,
            profile_id=account.social_profile_id,
            kind=BOOTSTRAP_KIND,
        ).first()
        assert job is not None

    def test_link_account_enqueues_bootstrap_job_when_unbootstrapped(self, owner, make_profile):
        profile = make_profile(owner, handle="atehofficial", platform="x")
        assert profile.bootstrapped_at is None

        account = ConnectedAccount.objects.create(
            user=owner,
            provider=Provider.PFM,
            external_account_id="pfm_acc_456",
            platform="x",
            handle="atehofficial",
            status=AccountStatus.ACTIVE,
        )

        res = link_account(owner, "pfm", account_id=account.external_account_id, profile=profile)
        assert res["profile_id"] == profile.pk

        job = BackgroundJob.objects.filter(
            user=owner,
            profile_id=profile.pk,
            kind=BOOTSTRAP_KIND,
        ).first()
        assert job is not None


@pytest.mark.django_db
class TestCrossNetworkAnchorPersonaAndNicheInheritance:
    def test_sparse_connection_inherits_primary_niche_and_voice(self, owner, make_profile):
        from unittest.mock import MagicMock

        from apps.intelligence.models import (
            NicheReport,
            ReportOrigin,
            ReportStatus,
            VoiceProfile,
            VoiceSource,
        )
        from apps.intelligence.repos.reports import ReportRepo
        from apps.intelligence.tasks import _inherit_anchor_voice_if_available

        # 1. User has a rich profile on X (e.g. 50 posts) with an active voice and niche
        profile_x = make_profile(owner, handle="atehofficial", platform="x")
        VoiceProfile.objects.create(
            profile=profile_x,
            platform="x",
            version=1,
            is_current=True,
            source=VoiceSource.POSTS,
            payload={"tone": "punchy, analytical, authoritative", "rules": ["lead with a strong hook"]},
        )
        pref_x = NichePreference.objects.create(
            profile=profile_x,
            niche_key="ai-agents:global",
            title="AI & Agentic Automation",
            source=NicheSource.INFERRED,
            is_active=True,
        )
        NichePreferenceKeyword.objects.create(preference=pref_x, keyword="ai agents")
        NichePreferenceKeyword.objects.create(preference=pref_x, keyword="automation")

        # And a validated niche report on X
        report_x = NicheReport.objects.create(
            profile=profile_x,
            query="AI & Agentic Automation",
            niche="ai-agents:global",
            status=ReportStatus.OK,
            posts_analyzed=30,
            winner_count=5,
            peers_analyzed=3,
            report={"frameworks": [{"title": "Problem-Agitate-Solve"}]},
            origin=ReportOrigin.PIPELINE,
        )

        # 2. User now connects LinkedIn, which has only 4 posts
        profile_linkedin = make_profile(owner, handle="atehofficial", platform="linkedin")
        sparse_posts = [
            DummyPost("Excited to join LinkedIn!"),
            DummyPost("Working on some tech projects."),
            DummyPost("Happy Monday everyone."),
            DummyPost("Great meeting today."),
        ]

        wiring = SimpleNamespace(
            competitors=SimpleNamespace(
                pipeline=SimpleNamespace(social=MagicMock(), config=AIConfig()),
            ),
            chain=None,
            config=AIConfig(),
        )

        # Run niche & competitor discovery on LinkedIn
        res = async_to_sync(_ensure_niche_and_competitors)(wiring, profile_linkedin.pk, sparse_posts)

        # A) Must NOT rewrite the persona or create a random niche: it inherits the primary niche!
        assert res["niche"] == "AI & Agentic Automation"
        assert res["niche_key"] == "ai-agents:global"

        pref_linkedin = NichePreference.objects.filter(profile=profile_linkedin, is_active=True).first()
        assert pref_linkedin is not None
        assert pref_linkedin.title == "AI & Agentic Automation"
        assert NichePreferenceKeyword.objects.filter(preference=pref_linkedin).count() == 2

        # B) Voice inheritance: when bootstrap runs on the sparse profile, it inherits anchor voice
        inherited = _inherit_anchor_voice_if_available(profile_linkedin.pk)
        assert inherited is not None
        assert inherited.status == "inherited"

        linkedin_voice = VoiceProfile.objects.filter(profile=profile_linkedin, is_current=True).first()
        assert linkedin_voice is not None
        assert linkedin_voice.payload["tone"] == "punchy, analytical, authoritative"

        # C) Cross-network report fallback: ReportRepo.latest_report for LinkedIn returns the rich X report!
        repo = ReportRepo()
        latest = async_to_sync(repo.latest_report)(profile_linkedin.pk)
        assert latest is not None
        assert latest.id == report_x.pk
        assert latest.query == "AI & Agentic Automation"

    def test_4_tier_competitor_grading_spectrum_and_details(self, owner, make_profile):
        profile = make_profile(owner, handle="atehofficial", platform="x")
        posts = [DummyPost("Building autonomous tech products #saas #nigeria")]
        wiring = SimpleNamespace(
            competitors=SimpleNamespace(
                pipeline=SimpleNamespace(social=MagicMock(), config=AIConfig()),
            ),
            chain=None,
            config=AIConfig(),
        )

        res = async_to_sync(_ensure_niche_and_competitors)(wiring, profile.pk, posts)
        assert "competitors" in res
        assert "competitor_details" in res
        assert len(res["competitor_details"]) > 0

        # Check NichePreferenceHandle database rows
        pref = NichePreference.objects.filter(profile=profile, is_active=True).first()
        assert pref is not None
        handles = list(NichePreferenceHandle.objects.filter(preference=pref).order_by("id"))
        assert len(handles) > 0

        # Verify 4-tier roles & grading scores
        roles = [h.peer_role for h in handles]
        assert "direct_competitor" in roles
        assert "parallel_founder" in roles
        for h in handles:
            assert 0.0 <= h.grading_score <= 1.0
            assert "geo_alignment" in h.relevance_breakdown
            assert isinstance(h.ecosystem_tags, list)
