import pytest
from asgiref.sync import sync_to_async
from django.db import connection, connections
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.chat import services
from apps.chat.models import ChatMessage
from apps.profiles.models import SocialHandle, SocialProfile
from lumi_ai.ports import ChatMessageIn

pytestmark = pytest.mark.django_db


@pytest.fixture
def profile():
    user = User.objects.create_user("chat@example.com")
    handle = SocialHandle.objects.create(platform="x", handle_normalized="chatty")
    return SocialProfile.objects.create(user=user, handle=handle)


def add(profile, role, text="hi", **kw):
    return services.append_message(
        profile.pk, ChatMessageIn(role=role, content=text, **kw)
    )


def test_append_round_trips_every_field(profile):
    mid = add(
        profile,
        "assistant",
        "answer",
        tool_calls=[{"id": "c1", "name": "search"}],
        tools_used=["search"],
        reason="needed data",
    )
    add(profile, "tool", "result", tool_name="search", tool_call_id="c1")
    first, second = services.history(profile.pk, 10)
    assert first.id == mid
    assert first.tool_calls == ({"id": "c1", "name": "search"},)
    assert (first.tools_used, first.reason) == (("search",), "needed data")
    assert (second.role, second.tool_name, second.tool_call_id) == (
        "tool",
        "search",
        "c1",
    )


def test_history_is_the_last_n_oldest_first_with_tool_rows(profile):
    ids = [add(profile, "user", str(i)) for i in range(5)]
    add(profile, "tool", "t", tool_name="x", tool_call_id="1")
    out = services.history(profile.pk, 3)
    assert [m.role for m in out] == ["user", "user", "tool"]
    assert [m.id for m in out[:2]] == ids[-2:]


def test_history_page_hides_tool_rows_and_pages_with_before(profile):
    ids = []
    for i in range(6):
        ids.append(add(profile, "user" if i % 2 == 0 else "assistant", str(i)))
        add(profile, "tool", "t", tool_name="x", tool_call_id=str(i))
    page = services.history_page(profile.pk, limit=2)
    assert [m.content for m in page] == ["4", "5"]
    older = services.history_page(profile.pk, limit=2, before=page[0].id)
    assert [m.content for m in older] == ["2", "3"]
    assert services.history_page(profile.pk, limit=5, before=ids[0]) == []


@pytest.mark.parametrize(
    ("asked", "expected"), [(0, 1), (-4, 1), (10_000, services.MAX_LIMIT)]
)
def test_limit_is_clamped(profile, asked, expected):
    for _ in range(3):
        add(profile, "user")
    assert len(services.history(profile.pk, asked)) == min(3, expected)


def test_histories_are_separate_per_profile_and_clear_is_scoped(profile):
    other = SocialProfile.objects.create(
        user=profile.user,
        handle=SocialHandle.objects.create(platform="x", handle_normalized="o"),
    )
    add(profile, "user")
    services.append_message(other.pk, ChatMessageIn(role="user", content="mine"))
    assert services.clear_history(profile.pk) == 1
    assert services.history(profile.pk, 5) == []
    assert [m.content for m in services.history(other.pk, 5)] == ["mine"]


def test_history_uses_one_query(profile):
    for _ in range(20):
        add(profile, "assistant", tools_used=["a"])
    with CaptureQueriesContext(connection) as ctx:
        services.history(profile.pk, 50)
    assert len(ctx) == 1


def test_role_check_is_enforced_by_the_database(profile):
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        ChatMessage.objects.create(profile=profile, role="system", content="x")


@pytest.mark.django_db(transaction=True)
async def test_async_twins(profile):
    try:
        mid = await services.aappend(
            profile.pk, ChatMessageIn(role="user", content="a")
        )
        assert [m.id for m in await services.ahistory(profile.pk, 5)] == [mid]
        assert await services.aclear_history(profile.pk) == 1
    finally:
        await sync_to_async(connections.close_all, thread_sensitive=True)()
