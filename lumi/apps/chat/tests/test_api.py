"""``/api/v1/chat/*`` against Postgres, with a fake agent runtime behind the seam."""

import json

import pytest
from asgiref.sync import async_to_sync
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.chat import services
from apps.chat.models import ChatMessage
from apps.core import agent_runtime as runtime
from lumi_ai.agent.result import SSEEvent, ToolExecution, TurnResult
from lumi_ai.ports import ChatMessageIn

pytestmark = pytest.mark.django_db
BASE = "/api/v1/chat"


class FakeRuntime:
    def __init__(self):
        self.calls = []
        self.title = None

    async def run_turn(self, profile_id, message):
        self.calls.append((profile_id, message))
        return TurnResult(
            content="listo",
            tool_calls_made=("get_analytics",),
            tool_executions=(
                ToolExecution("get_analytics", {"days": 7}, sample_posts=[{"id": 1}]),
            ),
        )

    async def stream_turn(self, profile_id, message):
        self.calls.append((profile_id, message))
        yield SSEEvent(
            "tool_start", {"tool": "get_analytics", "arguments": {}, "reason": "r"}
        )
        yield SSEEvent("tool_done", {"tool": "get_analytics", "sample_posts": []})
        yield SSEEvent("done", {"content": "listo", "tool_executions": []})

    async def generate_title(self, message):
        if isinstance(self.title, Exception):
            raise self.title
        return self.title


@pytest.fixture
def fake():
    fake = FakeRuntime()
    runtime.set_runtime(fake)
    yield fake
    runtime.set_runtime(None)


def say(profile, role, text):
    return services.append_message(profile.pk, ChatMessageIn(role=role, content=text))


def test_every_route_requires_a_token(client, profile):
    for method, path in [
        ("post", BASE),
        ("post", f"{BASE}/stream"),
        ("get", f"{BASE}/history?profile_id={profile.pk}"),
        ("delete", f"{BASE}/history?profile_id={profile.pk}"),
        ("post", f"{BASE}/title"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path


def test_a_foreign_profile_is_a_404_and_never_reaches_the_agent(
    stranger_api, profile, fake
):
    body = {"profile_id": profile.pk, "message": "hi"}
    assert stranger_api.post(BASE, body, format="json").status_code == 404
    assert stranger_api.post(f"{BASE}/stream", body, format="json").status_code == 404
    assert (
        stranger_api.get(f"{BASE}/history?profile_id={profile.pk}").status_code == 404
    )
    assert (
        stranger_api.delete(f"{BASE}/history?profile_id={profile.pk}").status_code
        == 404
    )
    assert fake.calls == []


def test_profile_id_is_required_everywhere(api, fake):
    for response in [
        api.post(BASE, {"message": "hi"}, format="json"),
        api.post(f"{BASE}/stream", {"message": "hi"}, format="json"),
        api.get(f"{BASE}/history"),
        api.delete(f"{BASE}/history"),
    ]:
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation_error"
    assert fake.calls == []


@pytest.mark.parametrize("message", ["", "   ", "x" * 8001])
def test_bad_messages_are_rejected(api, profile, fake, message):
    body = {"profile_id": profile.pk, "message": message}
    assert api.post(BASE, body, format="json").status_code == 400
    assert api.post(f"{BASE}/stream", body, format="json").status_code == 400
    assert fake.calls == []


def test_chat_runs_a_turn_and_shapes_the_answer(api, profile, fake):
    response = api.post(
        BASE, {"profile_id": profile.pk, "message": " hola "}, format="json"
    )
    assert response.status_code == 200
    assert response.json() == {
        "role": "assistant",
        "content": "listo",
        "tool_calls_made": ["get_analytics"],
        "tool_executions": [
            {
                "name": "get_analytics",
                "arguments": {"days": 7},
                "sample_posts": [{"id": 1}],
            }
        ],
    }
    assert fake.calls == [(profile.pk, "hola")]


def test_stream_sends_sse_events_with_the_right_headers(api, profile, fake):
    response = api.post(
        f"{BASE}/stream", {"profile_id": profile.pk, "message": "hi"}, format="json"
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    assert response["Cache-Control"] == "no-cache"
    assert response["X-Accel-Buffering"] == "no"

    async def read():
        return b"".join([chunk async for chunk in response.streaming_content]).decode()

    text = async_to_sync(read)()
    events = [
        json.loads(block[len("data: ") :]) for block in text.strip().split("\n\n")
    ]
    assert [e["type"] for e in events] == ["tool_start", "tool_done", "done"]
    assert events[-1]["content"] == "listo"


def test_stream_accepts_a_strict_event_stream_accept_header(api, profile, fake):
    response = api.post(
        f"{BASE}/stream",
        {"profile_id": profile.pk, "message": "hi"},
        format="json",
        HTTP_ACCEPT="text/event-stream",
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")


def test_a_strict_event_stream_accept_still_gets_the_json_error(api, profile, fake):
    response = api.post(
        f"{BASE}/stream",
        {"profile_id": profile.pk, "message": ""},
        format="json",
        HTTP_ACCEPT="text/event-stream",
    )
    assert response.status_code == 400
    assert json.loads(response.content)["error"]["code"] == "validation_error"


def test_the_other_chat_routes_still_refuse_an_event_stream_accept(api, profile, fake):
    response = api.post(
        BASE,
        {"profile_id": profile.pk, "message": "hi"},
        format="json",
        HTTP_ACCEPT="text/event-stream",
    )
    assert response.status_code == 406


def test_without_a_runtime_the_agent_routes_answer_503(api, profile, settings):
    settings.LUMI_CHAT_RUNTIME = "apps.does_not_exist"
    runtime.set_runtime(None)
    for path in (BASE, f"{BASE}/stream"):
        response = api.post(
            path, {"profile_id": profile.pk, "message": "hi"}, format="json"
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "chat.unavailable"
    # history does not need the agent
    assert api.get(f"{BASE}/history?profile_id={profile.pk}").status_code == 200


def test_history_lists_user_and_assistant_oldest_first(api, profile):
    say(profile, "user", "one")
    services.append_message(
        profile.pk,
        ChatMessageIn(role="tool", content="{}", tool_name="t", tool_call_id="c"),
    )
    say(profile, "assistant", "two")
    body = api.get(f"{BASE}/history?profile_id={profile.pk}").json()
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("user", "one"),
        ("assistant", "two"),
    ]
    assert set(body["messages"][0]) == {"id", "role", "content", "created_at"}


def test_history_paginates_with_limit_and_before(api, profile):
    ids = [say(profile, "user", f"m{i}") for i in range(6)]
    page = api.get(f"{BASE}/history?profile_id={profile.pk}&limit=2").json()["messages"]
    assert [m["content"] for m in page] == ["m4", "m5"]
    older = api.get(
        f"{BASE}/history?profile_id={profile.pk}&limit=2&before={ids[4]}"
    ).json()["messages"]
    assert [m["content"] for m in older] == ["m2", "m3"]


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=201", "limit=x", "before=0", "before=x"]
)
def test_history_rejects_bad_paging(api, profile, query):
    response = api.get(f"{BASE}/history?profile_id={profile.pk}&{query}")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_history_is_one_query_however_long(api, profile):
    api.get(
        f"{BASE}/history?profile_id={profile.pk}"
    )  # stamps the token's last_used_at
    for i in range(5):
        say(profile, "user", f"m{i}")
    with CaptureQueriesContext(connection) as small:
        api.get(f"{BASE}/history?profile_id={profile.pk}")
    for i in range(40):
        say(profile, "assistant", f"n{i}")
    with CaptureQueriesContext(connection) as big:
        assert (
            len(api.get(f"{BASE}/history?profile_id={profile.pk}").json()["messages"])
            == 45
        )
    assert len(big) == len(small)


def test_delete_history_clears_only_that_profile(api, owner, profile, make_profile):
    other = make_profile(owner, "second")
    say(profile, "user", "a")
    say(other, "user", "b")
    assert api.delete(f"{BASE}/history?profile_id={profile.pk}").status_code == 204
    assert list(ChatMessage.objects.values_list("profile_id", flat=True)) == [other.pk]


def test_title_uses_the_runtime_then_cleans_it(api, fake):
    fake.title = '"**Growth Plan.**"'
    assert api.post(
        f"{BASE}/title", {"message": "help me grow"}, format="json"
    ).json() == {"title": "Growth Plan"}


@pytest.mark.parametrize("answer", [None, "", "x" * 40, RuntimeError("down")])
def test_title_falls_back_to_the_first_words(api, fake, answer):
    fake.title = answer
    response = api.post(
        f"{BASE}/title", {"message": "how do i grow my audience fast"}, format="json"
    )
    assert response.json() == {"title": "How Do I Grow"}


def test_title_works_with_no_runtime_at_all(api, settings):
    settings.LUMI_CHAT_RUNTIME = "apps.does_not_exist"
    runtime.set_runtime(None)
    response = api.post(f"{BASE}/title", {"message": "plan my week"}, format="json")
    assert response.json() == {"title": "Plan My Week"}


def test_chat_routes_are_rate_limited_per_user(
    api, stranger_api, profile, fake, monkeypatch
):
    from apps.core.throttles import ChatUserThrottle

    monkeypatch.setattr(ChatUserThrottle, "THROTTLE_RATES", {"chat": "2/min"})
    body = {"profile_id": profile.pk, "message": "hi"}
    assert [api.post(BASE, body, format="json").status_code for _ in range(3)] == [
        200,
        200,
        429,
    ]
    assert (
        stranger_api.post(f"{BASE}/title", {"message": "x"}, format="json").status_code
        == 200
    )
