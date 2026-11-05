"""Real provider calls. Skipped unless LUMI_RUN_LIVE=1 and the variable named in each test is set.

There is deliberately no live test for X: every X call spends prepaid credits.
"""

from __future__ import annotations

import os

import pytest

from apps.connections.config import ConnectionsConfig
from apps.connections.providers.base import TokenSet
from apps.connections.providers.registry import build_provider

pytestmark = pytest.mark.live


def _need(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


async def test_meta_user_token_can_list_pages() -> None:
    token = _need("META_TEST_USER_TOKEN")
    provider = build_provider("meta", ConnectionsConfig.from_env(os.environ))
    pages = await provider.list_accounts(TokenSet(access_token=token))
    assert all(p.external_id for p in pages)


async def test_linkedin_token_reads_userinfo() -> None:
    token = _need("LINKEDIN_TEST_ACCESS_TOKEN")
    provider = build_provider("linkedin", ConnectionsConfig.from_env(os.environ))
    account = await provider.get_account(TokenSet(access_token=token))
    assert account.external_id
