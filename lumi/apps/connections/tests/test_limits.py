"""Publish limits come from ``lumi_ai.generation.platforms``, never from a local copy."""

from __future__ import annotations

import httpx
import pytest

from apps.connections.config import ConnectionsConfig
from apps.connections.errors import ValidationFailed
from apps.connections.providers.base import PublishDraft
from apps.connections.providers.registry import build_provider
from lumi_ai.generation.platforms import rules_for

ENV = {
    "META_APP_ID": "i",
    "META_APP_SECRET": "s",
    "LINKEDIN_CLIENT_ID": "i",
    "LINKEDIN_CLIENT_SECRET": "s",
    "X_CLIENT_ID": "i",
    "X_CLIENT_SECRET": "s",
}
PROVIDER_OF = {"facebook": "meta", "linkedin": "linkedin", "x": "x"}


def provider(platform: str):
    return build_provider(
        PROVIDER_OF[platform],
        ConnectionsConfig.from_env(ENV),
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )


@pytest.mark.parametrize("platform", ["x", "linkedin", "facebook"])
def test_capabilities_use_the_generator_limit(platform) -> None:
    assert (
        provider(platform).capabilities().max_text_length
        == rules_for(platform).hard_limit
    )


def test_the_limits_are_the_documented_numbers() -> None:
    assert {p: rules_for(p).hard_limit for p in ("x", "linkedin", "facebook")} == {
        "x": 280,
        "linkedin": 3000,
        "facebook": 63_206,
    }
    assert rules_for("facebook").limit_is_official is False
    assert rules_for("instagram").hard_limit == 2200
    assert rules_for("instagram").hashtags_max == 5
    assert rules_for("tiktok").utf16_length is True


@pytest.mark.parametrize("platform", ["x", "linkedin", "facebook"])
def test_exactly_the_limit_passes_and_one_more_fails(platform) -> None:
    limit = rules_for(platform).hard_limit
    p = provider(platform)
    p.validate_draft(PublishDraft(text="a" * limit))
    with pytest.raises(ValidationFailed, match=str(limit)):
        p.validate_draft(PublishDraft(text="a" * (limit + 1)))


def test_the_error_names_the_network_and_its_limit() -> None:
    with pytest.raises(ValidationFailed, match=r"281 characters and X allows 280"):
        provider("x").validate_draft(PublishDraft(text="a" * 281))


def test_an_empty_post_is_rejected() -> None:
    with pytest.raises(ValidationFailed, match="empty"):
        provider("x").validate_draft(PublishDraft(text="   "))


def test_no_local_copy_of_the_limits_is_left() -> None:
    import apps.connections.providers.linkedin as li
    import apps.connections.providers.meta as me
    from apps.connections.providers import x

    assert not any(hasattr(m, "MAX_TEXT") for m in (li, me, x))
