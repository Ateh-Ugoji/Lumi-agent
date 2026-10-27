"""Failure-path tests for the listening tools.

A flaky Xpoz upstream (5xx / network) used to escape the tool, abort the agent
turn, and reach the UI as an empty "success". These pin the new contract:
transient failures are retried once, everything else is reported as an honest
error payload — never a crash, never fabricated analysis.
"""

from contextlib import asynccontextmanager

import httpx

from app.services import framework_corpus, handle_db
from app.tools import listening


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.xpoz.ai/api/data/twitter/posts/live")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(
        f"Server error '{status}'", request=request, response=response
    )


class _FakeScalarResult:
    def first(self):
        return None


class _FakeSession:
    async def exec(self, _stmt):
        return _FakeScalarResult()

    def add(self, _row):
        pass

    async def commit(self):
        pass

    async def refresh(self, _row):
        pass


@asynccontextmanager
async def _fake_session_scope():
    yield _FakeSession()


async def _noop_scanned(*_args, **_kwargs):
    return 0


def _silence_side_effects(monkeypatch) -> None:
    """Keep DB, Chroma and retry delays out of these tests."""
    monkeypatch.setattr("app.database.session_scope", _fake_session_scope)
    monkeypatch.setattr(listening, "session_scope", _fake_session_scope)
    monkeypatch.setattr(handle_db, "remember_scanned", _noop_scanned)
    monkeypatch.setattr(handle_db, "remember", lambda *_a, **_k: 0)
    monkeypatch.setattr(listening, "XPOZ_RETRY_BACKOFF_SECONDS", 0)


def _install_framework_patches(monkeypatch) -> None:
    monkeypatch.setattr(framework_corpus, "upsert_framework", lambda *_a, **_k: False)
    monkeypatch.setattr(framework_corpus, "upsert_peer_posts", lambda *_a, **_k: 0)


async def _no_llm_tagging(_posts):
    """Keep the pipeline's blind-tagging stage off the network in these tests."""
    return []


def _patch_pipeline(monkeypatch) -> None:
    monkeypatch.setattr("app.services.peer_pipeline.tag_posts", _no_llm_tagging)


def _live_page(username: str, n: int = 3):
    """A small but well-formed account: real dates, no metrics surprises."""
    return (
        [
            {
                "id": f"{username}-{i}",
                "text": f"post {i} from {username}",
                "authorUsername": username,
                "impressionCount": 100 * i,
                "createdAt": "2026-10-01T12:00:00+00:00",
            }
            for i in range(1, n + 1)
        ],
        None,
        False,
    )


async def test_transient_500_is_retried_once_then_succeeds(monkeypatch):
    _silence_side_effects(monkeypatch)
    _install_framework_patches(monkeypatch)
    _patch_pipeline(monkeypatch)
    calls = {"search": 0, "pages": 0}

    class FakeXpoz:
        async def search_live_posts(self, query, limit=25):
            calls["search"] += 1
            if calls["search"] == 1:
                raise _http_error(500)
            return [
                {"id": "1", "text": "win", "impressionCount": 5000, "authorUsername": "peer_one"}
            ]

        async def get_user_live_posts_page(self, username, *, limit=20, cursor=None):
            calls["pages"] += 1
            return _live_page(username)

        async def aclose(self):
            pass

    monkeypatch.setattr("app.services.xpoz.XpozClient", FakeXpoz)

    result = await listening.discover_and_extract_niche_frameworks(
        profile_id=1, query="tech"
    )

    assert calls["search"] == 2, "a transient 5xx is retried exactly once"
    assert "error" not in result
    assert calls["pages"] >= 1, "the pipeline reads each discovered account's own posts"
    assert result["qualifying_posts_count"] == 0
    assert result["report_status"] == "insufficient_data", (
        "a 3-post account has no reliable baseline — the run says so instead of guessing"
    )
    assert result["framework_insights"]["winning_frameworks"] == [], "no canned frameworks"
    assert result["framework_insights"]["content_pillars"] == [], "no canned pillars"


async def test_persistent_upstream_failure_returns_honest_payload(monkeypatch):
    _silence_side_effects(monkeypatch)
    calls = {"search": 0, "pipeline": 0}

    class FakeXpoz:
        async def search_live_posts(self, query, limit=25):
            calls["search"] += 1
            raise _http_error(500)

        async def aclose(self):
            pass

    async def pipeline_spy(**_kwargs):
        calls["pipeline"] += 1
        raise AssertionError("the pipeline must not run on a discovery that failed")

    monkeypatch.setattr("app.services.xpoz.XpozClient", FakeXpoz)
    monkeypatch.setattr("app.services.peer_pipeline.run_peer_pipeline", pipeline_spy)

    result = await listening.discover_and_extract_niche_frameworks(
        profile_id=1, query="tech"
    )

    assert calls["search"] == 2, "two attempts, then give up"
    assert calls["pipeline"] == 0, "no pipeline analysis on a search that returned nothing"
    assert "HTTP 500" in result["error"]
    assert result["qualifying_posts_count"] == 0
    assert result["framework_insights"] == {}, "nothing analyzed stays empty, never canned"
    assert result["peer_framework_id"] is None, "no row is written on failure"


async def test_auth_failure_is_not_retried(monkeypatch):
    _silence_side_effects(monkeypatch)
    calls = {"search": 0}

    class FakeXpoz:
        async def search_live_posts(self, query, limit=25):
            calls["search"] += 1
            raise _http_error(401)

        async def aclose(self):
            pass

    monkeypatch.setattr("app.services.xpoz.XpozClient", FakeXpoz)

    result = await listening.discover_and_extract_niche_frameworks(
        profile_id=1, query="tech"
    )

    assert calls["search"] == 1, "a 4xx never heals on retry"
    assert "HTTP 401" in result["error"]
    assert "invalid" in result["error"]


async def test_niche_trends_reports_when_every_handle_fails(monkeypatch):
    _silence_side_effects(monkeypatch)

    class FakeXpoz:
        async def get_user_live_posts(self, username, limit=10):
            raise _http_error(500)

        async def aclose(self):
            pass

    monkeypatch.setattr("app.services.xpoz.XpozClient", FakeXpoz)

    result = await listening.check_niche_trends(
        profile_id=1, handles=["sama", "levelsio"], min_likes=50
    )

    assert result["new_matches_found"] == 0
    assert len(result["failed_handles"]) == 2
    assert "all 2" in result["error"], "an empty scan says why it is empty"
    assert result["viral_posts"] == []


async def test_partial_handle_failure_is_named_without_failing_the_scan(monkeypatch):
    _silence_side_effects(monkeypatch)

    class FakeXpoz:
        async def get_user_live_posts(self, username, limit=10):
            if username == "sama":
                raise _http_error(500)
            return [
                {"id": f"{username}-1", "text": "viral", "likeCount": 999, "authorUsername": username}
            ]

        async def aclose(self):
            pass

    monkeypatch.setattr("app.services.xpoz.XpozClient", FakeXpoz)

    result = await listening.check_niche_trends(
        profile_id=1, handles=["sama", "levelsio"], min_likes=50
    )

    assert result["new_matches_found"] == 1, "the healthy handle still scans"
    assert result["failed_handles"] == ["@sama: " + result["failed_handles"][0].split(": ", 1)[1]]
    assert "error" not in result, "a partial miss is a footnote, not a failure"


async def test_niche_trends_coerces_string_min_likes(monkeypatch):
    """Registry dispatch does no type coercion: the model can send `min_likes`
    as a JSON string ("50"), and the `int < str` compare used to kill the whole
    tool mid-scan before any post was checked (observed live 2026-10-21)."""
    _silence_side_effects(monkeypatch)

    class FakeXpoz:
        async def get_user_live_posts(self, username, limit=10):
            return [
                {
                    "id": f"{username}-1",
                    "text": "viral",
                    "likeCount": 999,
                    "authorUsername": username,
                }
            ]

        async def aclose(self):
            pass

    monkeypatch.setattr("app.services.xpoz.XpozClient", FakeXpoz)

    result = await listening.check_niche_trends(
        profile_id=1, handles=["sama"], min_likes="20"
    )

    assert result["new_matches_found"] == 1, "string threshold coerced, scan completes"
    assert "error" not in result
