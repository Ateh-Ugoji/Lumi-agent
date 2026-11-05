"""Constraint tests for chat_messages."""

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.chat.models import ChatMessage
from apps.profiles.models import SocialHandle, SocialProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def profile():
    user = User.objects.create_user("chat@example.com")
    handle = SocialHandle.objects.create(platform="x", handle_normalized="talker")
    return SocialProfile.objects.create(user=user, handle=handle)


def test_defaults_come_from_the_database(profile):
    message = ChatMessage.objects.create(profile=profile, role="user")
    message.refresh_from_db()
    assert message.content == ""
    assert message.created_at is not None
    assert message.tool_calls is None and message.tools_used is None


@pytest.mark.parametrize("role", ["user", "assistant", "tool"])
def test_known_roles(profile, role):
    ChatMessage.objects.create(profile=profile, role=role, content="hi")


@pytest.mark.parametrize("role", ["USER", "system", ""])
def test_unknown_roles_are_rejected(profile, role):
    with pytest.raises(IntegrityError), transaction.atomic():
        ChatMessage.objects.create(profile=profile, role=role)


def test_tool_columns_round_trip(profile):
    calls = [{"id": "call_1", "name": "get_posts", "arguments": {"limit": 5}}]
    ChatMessage.objects.create(
        profile=profile, role="assistant", tool_calls=calls, tools_used=["get_posts"]
    )
    ChatMessage.objects.create(
        profile=profile,
        role="tool",
        tool_name="get_posts",
        tool_call_id="call_1",
        reason="needed the latest posts",
        content="[]",
    )
    first, second = ChatMessage.objects.filter(profile=profile).order_by("id")
    assert first.tool_calls == calls and first.tools_used == ["get_posts"]
    assert second.tool_call_id == "call_1"


def test_clearing_history_is_one_delete(profile, django_assert_num_queries):
    for _ in range(3):
        ChatMessage.objects.create(profile=profile, role="user")
    with django_assert_num_queries(1):
        ChatMessage.objects.filter(profile=profile)._raw_delete(ChatMessage.objects.db)
    assert ChatMessage.objects.count() == 0


def test_deleting_the_profile_deletes_its_messages(profile):
    ChatMessage.objects.create(profile=profile, role="user")
    profile.delete()
    assert ChatMessage.objects.count() == 0
