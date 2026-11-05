from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from apps.connections.linkedin_social import LinkedInSocialData
from apps.connections.providers.base import AccountInfo, TokenSet
from lumi_ai import ports


@pytest.mark.django_db
class TestLinkedInSocialData:
    @pytest.mark.asyncio
    async def test_get_user_and_search_users(self):
        adapter = LinkedInSocialData()
        user = await adapter.get_user("ateh-ugoji")
        assert user is not None
        assert user.platform == "linkedin"
        assert user.handle == "ateh-ugoji"

        results = await adapter.search_users("ateh", 5)
        assert len(results) == 1
        assert results[0].handle == "ateh"

    def test_fetch_user_posts_via_connected_account(self, owner, make_profile):
        from asgiref.sync import async_to_sync

        profile = make_profile(owner, handle="ateh", platform="linkedin")
        adapter = LinkedInSocialData()

        fake_posts = [
            ports.PostIn(
                platform="linkedin",
                external_id="urn:li:share:12345",
                author_handle="ateh",
                text="Excited to announce our AI workflow engine",
                published_at=datetime.now(UTC),
            )
        ]

        mock_provider = AsyncMock()
        mock_provider.get_account.return_value = AccountInfo(
            external_id="12345", display_name="Ateh", status="active"
        )
        mock_provider.fetch_posts.return_value = fake_posts

        with patch("apps.connections.providers.registry.build_provider", return_value=mock_provider), \
             patch("apps.connections.models.ConnectedAccount.objects.filter") as mock_filter:
            mock_filter.return_value.first.return_value = type(
                "ConnectedAccountMock",
                (),
                {"tokens": TokenSet(access_token="valid_token", scopes=("r_member_social",))},
            )()

            posts = async_to_sync(adapter.fetch_user_posts)("ateh", since=None, limit=10)
            assert len(posts) == 1
            assert posts[0].platform == "linkedin"
            assert posts[0].external_id == "urn:li:share:12345"
            assert "AI workflow engine" in posts[0].text
