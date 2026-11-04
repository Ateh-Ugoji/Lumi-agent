from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.jobs import JobContext
from apps.intelligence.models import (
    NichePreference,
    NichePreferenceHandle,
    NicheSource,
)
from apps.intelligence.tasks import PEER_SYNC_KIND, sync_peer_posts, sync_peer_posts_task
from apps.profiles import services
from apps.profiles.models import HandleOrigin
from lumi_ai import ports


@pytest.mark.django_db
class TestPeerSyncTask:
    def test_sync_peer_posts_fetches_saves_and_indexes(self, owner, make_profile):
        profile = make_profile(owner, handle="atehofficial", platform="x")

        # Create active niche preference and tracked competitor handles
        pref = NichePreference.objects.create(
            profile=profile,
            niche_key="tech:ng",
            title="Nigerian Tech Founder & Creative Builder (Nigeria)",
            is_active=True,
            source=NicheSource.INFERRED,
        )
        h1 = services.get_or_create_handle("x", "timmyisagod", origin=HandleOrigin.NICHE)
        h2 = services.get_or_create_handle("x", "honour_can_code", origin=HandleOrigin.NICHE)
        NichePreferenceHandle.objects.create(preference=pref, handle_id=h1)
        NichePreferenceHandle.objects.create(preference=pref, handle_id=h2)

        sample_posts = [
            ports.PostIn(
                platform="x",
                external_id="post-timmy-1",
                text="Shipping products in public from Lagos",
                published_at=datetime.now(UTC),
                author_handle="timmyisagod",
                metrics=ports.PostMetrics(likes=80),
            )
        ]

        mock_social = SimpleNamespace(
            fetch_user_posts=AsyncMock(return_value=sample_posts)
        )
        mock_pipeline = SimpleNamespace(social=mock_social)
        mock_competitors = SimpleNamespace(pipeline=mock_pipeline)

        saved_rows = [
            ports.PeerPostOut(
                id=101,
                profile_id=profile.pk,
                platform="x",
                external_id="post-timmy-1",
                author_handle="timmyisagod",
                text="Shipping products in public from Lagos",
                published_at=datetime.now(UTC),
                url="https://x.com/timmyisagod/status/post-timmy-1",
                metrics=ports.PostMetrics(likes=80),
                media=(),
                niche_key="tech:ng",
                author_avatar_url="",
            )
        ]
        mock_peers_repo = SimpleNamespace(
            save_peer_posts=AsyncMock(return_value=saved_rows)
        )
        mock_indexer = SimpleNamespace(
            index_peer_posts=MagicMock(return_value=len(saved_rows))
        )

        mock_wiring = SimpleNamespace(
            competitors=mock_competitors,
            peers=mock_peers_repo,
            indexer=mock_indexer,
        )

        ctx = JobContext(
            id=uuid.uuid4(),
            user_id=owner.pk,
            profile_id=profile.pk,
            kind=PEER_SYNC_KIND,
            params={},
        )

        with patch("apps.intelligence.wiring.begin_run"), patch(
            "apps.intelligence.wiring.get_wiring", return_value=mock_wiring
        ):
            res = sync_peer_posts(ctx)

        assert res["handles_scanned"] == 2
        assert res["posts_saved"] == 1
        assert res["posts_indexed"] == 1
        assert mock_social.fetch_user_posts.call_count == 2
        mock_peers_repo.save_peer_posts.assert_called_once()
        mock_indexer.index_peer_posts.assert_called_once_with(saved_rows)

    def test_sync_peer_posts_task_enqueues_background_job(self, owner, make_profile):
        profile = make_profile(owner, handle="atehofficial", platform="x")
        with patch("apps.core.jobs.enqueue", return_value=(uuid.uuid4(), True)) as mock_enqueue:
            res = sync_peer_posts_task(profile_id=profile.pk)
            assert "job_id" in res
            mock_enqueue.assert_called_once()
