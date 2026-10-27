"""Tests for the shared handle DB writer (the main app's side of the MVP's store).

Chroma and Xpoz are fully faked — green with no network, no credits, and with
the real collection resolver disabled by default (autouse fixture), so no test
can ever reach the real store.
"""

from contextlib import asynccontextmanager

import pytest

from app.services import handle_db

# The real resolver, captured before the autouse fixture replaces it.
_real_collection = handle_db._collection


class FakeCollection:
    """Chroma collection subset: records upserts, serves existence checks."""

    def __init__(self, existing: set[str] | None = None):
        self.existing = set(existing or ())
        self.upserts: list[dict] = []

    def get(self, ids=None, include=None):
        return {"ids": [i for i in (ids or []) if i in self.existing]}

    def upsert(self, ids, documents, metadatas):
        self.upserts.append({"ids": ids, "documents": documents, "metadatas": metadatas})
        self.existing.update(ids)


class BrokenCollection:
    def get(self, ids=None, include=None):
        raise RuntimeError("chroma down")

    def upsert(self, ids, documents, metadatas):
        raise RuntimeError("chroma down")


@pytest.fixture(autouse=True)
def _no_real_store(monkeypatch):
    """Default: store off. Tests that need one install their own fake."""
    monkeypatch.setattr(handle_db, "_collection", lambda: None)
    yield


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


def _httpx_client_returning(results, status_code: int = 200):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            return _FakeResponse({"results": results}, status_code)

    return Client


# ---------------------------------------------------------------- remember()


async def test_remember_writes_mvp_compatible_rows(monkeypatch):
    fake = FakeCollection()
    monkeypatch.setattr(handle_db, "_collection", lambda: fake)

    written = handle_db.remember(
        [
            {
                "handle": "@Karpathy",
                "display_name": "Andrej",
                "avatar_url": "https://img/pfp.jpg",
                "followers": 1234,
            },
            {"handle": "noone", "followers": None},  # missing data stays missing
            {"handle": "   "},  # skipped
        ],
        origin="niche",
        query="indie hackers",
    )

    assert written == 2
    batch = fake.upserts[0]
    # id/document scheme must match the MVP's rows exactly
    assert batch["ids"] == ["x:karpathy", "x:noone"]
    assert batch["documents"] == ["Karpathy", "noone"]
    first, second = batch["metadatas"]
    assert first == {
        "handle": "Karpathy",
        "platform": "x",
        "display_name": "Andrej",
        "avatar_url": "https://img/pfp.jpg",
        "followers": 1234,
        "selected_query": "indie hackers",
        "origin": "niche",
        "ts": first["ts"],
    }
    assert isinstance(first["ts"], int)
    assert second["followers"] == -1, "absent followers -> NULL sentinel, never a fabricated 0"
    assert second["display_name"] == "" and second["avatar_url"] == ""


async def test_remember_is_add_if_absent(monkeypatch):
    fake = FakeCollection(existing={"x:karpathy"})
    monkeypatch.setattr(handle_db, "_collection", lambda: fake)

    written = handle_db.remember(
        [{"handle": "karpathy"}, {"handle": "karpov"}], origin="niche"
    )

    assert written == 1, "existing rows are never rewritten (origin/data preserved)"
    assert fake.upserts[0]["ids"] == ["x:karpov"]


async def test_remember_never_raises(monkeypatch):
    monkeypatch.setattr(handle_db, "_collection", lambda: BrokenCollection())
    assert handle_db.remember([{"handle": "karpathy"}], origin="niche") == 0


async def test_no_chroma_config_is_a_noop(monkeypatch):
    for var in ("MVP_CHROMA_API_KEY", "MVP_CHROMA_TENANT", "MVP_CHROMA_DATABASE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(handle_db, "_collection", _real_collection)
    handle_db._reset_for_tests()
    try:
        assert handle_db.remember([{"handle": "karpathy"}], origin="niche") == 0
    finally:
        handle_db._reset_for_tests()


# ------------------------------------------------------- remember_scanned()


async def test_scanned_handles_enrich_only_unknown_within_cap(monkeypatch):
    fake = FakeCollection(existing={"x:sama"})
    monkeypatch.setattr(handle_db, "_collection", lambda: fake)
    monkeypatch.setenv("HANDLE_DB_ENRICH_LIMIT", "1")

    enriched: list[str] = []

    async def fake_profile(handle):
        enriched.append(handle)
        return {
            "handle": handle,
            "display_name": f"{handle} dev",
            "avatar_url": f"https://img/{handle}",
            "followers": 50,
        }

    monkeypatch.setattr(handle_db, "_user_profile", fake_profile)

    written = await handle_db.remember_scanned(
        ["sama", "karpathy", "levelsio"], origin="niche"
    )

    assert enriched == ["karpathy"], "known handle never re-enriched; cap = 1 new handle"
    assert written == 2
    batch = fake.upserts[0]
    by_id = dict(zip(batch["ids"], batch["metadatas"], strict=True))
    assert by_id["x:karpathy"]["avatar_url"] == "https://img/karpathy"
    assert by_id["x:karpathy"]["followers"] == 50
    assert by_id["x:levelsio"]["avatar_url"] == "" and by_id["x:levelsio"]["followers"] == -1


async def test_scanned_handles_zero_limit_saves_handles_only(monkeypatch):
    fake = FakeCollection()
    monkeypatch.setattr(handle_db, "_collection", lambda: fake)
    monkeypatch.setenv("HANDLE_DB_ENRICH_LIMIT", "0")

    async def boom(handle):
        raise AssertionError("enrichment must not run when the cap is 0")

    monkeypatch.setattr(handle_db, "_user_profile", boom)

    written = await handle_db.remember_scanned(["sama"], origin="niche")

    assert written == 1
    assert fake.upserts[0]["metadatas"][0]["followers"] == -1


async def test_scanned_handles_no_enrichment_when_store_is_down(monkeypatch):
    calls: list[str] = []

    async def spy(handle):
        calls.append(handle)

    monkeypatch.setattr(handle_db, "_user_profile", spy)

    written = await handle_db.remember_scanned(["sama"], origin="niche")

    assert written == 0
    assert calls == [], "no credits may be spent when the store cannot persist the result"


# ---------------------------------------------------------- _user_profile()


async def test_user_profile_requires_exact_username_match(monkeypatch):
    monkeypatch.setenv("XPOZ_API_KEY", "test-key")
    monkeypatch.setattr(
        handle_db.httpx, "AsyncClient",
        _httpx_client_returning(
            [{"username": "karpathydev", "name": "Someone else", "followersCount": 99}]
        ),
    )
    assert await handle_db._user_profile("karpathy") is None, (
        "a fuzzy top-hit is a different person — their picture must never be stored"
    )

    monkeypatch.setattr(
        handle_db.httpx, "AsyncClient",
        _httpx_client_returning(
            [{"username": "Karpathy", "name": "Andrej", "profileImageUrl": "u", "followersCount": 7}]
        ),
    )
    profile = await handle_db._user_profile("karpathy")
    assert profile == {
        "handle": "Karpathy",
        "display_name": "Andrej",
        "avatar_url": "u",
        "followers": 7,
    }


async def test_user_profile_rotates_keys_on_auth_failure(monkeypatch):
    monkeypatch.setenv("XPOZ_API_KEY", "k1")
    monkeypatch.setenv("XPOZ_API_KEY_2", "k2")
    attempts: list[str | None] = []

    class Client:
        def __init__(self, **kwargs):
            self._headers = kwargs.get("headers") or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            attempts.append(self._headers.get("Authorization"))
            if len(attempts) == 1:
                return _FakeResponse({}, status_code=401)
            return _FakeResponse(
                {"results": [{"username": "karpathy", "name": "A", "profileImageUrl": "u", "followersCount": 7}]}
            )

    monkeypatch.setattr(handle_db.httpx, "AsyncClient", Client)

    profile = await handle_db._user_profile("karpathy")
    assert profile["followers"] == 7
    assert attempts == ["Bearer k1", "Bearer k2"]


# ------------------------------------------------------- tool wiring


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


def _spy_handle_db(monkeypatch):
    calls: dict[str, list] = {"scanned": [], "remembered": []}

    async def fake_scanned(handles, *, origin, query=""):
        calls["scanned"].append((list(handles), origin))
        return 0

    def fake_remember(items, *, origin, query=""):
        calls["remembered"].append(([i["handle"] for i in items], origin, query))
        return len(items)

    monkeypatch.setattr(handle_db, "remember_scanned", fake_scanned)
    monkeypatch.setattr(handle_db, "remember", fake_remember)
    return calls


async def test_check_niche_trends_persists_every_user_it_searches(monkeypatch):
    from app.tools import listening

    calls = _spy_handle_db(monkeypatch)

    class FakeXpoz:
        async def get_user_live_posts(self, username, limit=10):
            return [
                {"id": f"{username}-1", "text": "viral", "likeCount": 999, "authorUsername": username},
                {"id": f"{username}-2", "text": "quiet", "likeCount": 1, "authorUsername": "quiet_author"},
                {"id": f"{username}-3", "text": "other", "likeCount": 500, "authorUsername": "OtherCreator"},
            ]

        async def aclose(self):
            pass

    monkeypatch.setattr("app.services.xpoz.XpozClient", FakeXpoz)
    monkeypatch.setattr(listening, "session_scope", _fake_session_scope)

    result = await listening.check_niche_trends(
        profile_id=1, handles=["sama", "levelsio"], min_likes=50
    )

    assert result["new_matches_found"] == 4
    scanned, origin = calls["scanned"][0]
    assert scanned == ["sama", "levelsio"], "every tracked account is persisted"
    assert origin == "niche"
    remembered, origin, _ = calls["remembered"][0]
    assert set(remembered) == {"sama", "levelsio", "quiet_author", "OtherCreator"}, (
        "authors of viral AND quiet posts are saved — anything the search surfaced"
    )
    assert origin == "niche"


async def test_check_niche_trends_survives_handle_db_failure(monkeypatch):
    from app.tools import listening

    async def boom(handles, *, origin, query=""):
        raise RuntimeError("handle db down")

    monkeypatch.setattr(handle_db, "remember_scanned", boom)
    monkeypatch.setattr(handle_db, "remember", boom)

    class FakeXpoz:
        async def get_user_live_posts(self, username, limit=10):
            return [{"id": f"{username}-1", "text": "viral", "likeCount": 999, "authorUsername": username}]

        async def aclose(self):
            pass

    monkeypatch.setattr("app.services.xpoz.XpozClient", FakeXpoz)
    monkeypatch.setattr(listening, "session_scope", _fake_session_scope)

    result = await listening.check_niche_trends(profile_id=1, handles=["sama"], min_likes=50)

    assert result["new_matches_found"] == 1, "the scan itself must never fail over the handle DB"


async def test_frameworks_search_persists_every_author(monkeypatch):
    from app.services import framework_corpus
    from app.tools import listening

    calls = _spy_handle_db(monkeypatch)

    class FakeXpoz:
        async def search_live_posts(self, query, limit=25):
            return [
                {"id": "1", "text": "win", "impressionCount": 5000, "authorUsername": "peer_one"},
                {"id": "2", "text": "small", "impressionCount": 10, "authorUsername": "peer_two"},
                {"id": "3", "text": "win", "impressionCount": 9000, "authorUsername": "peer_one"},
            ]

        async def get_user_live_posts_page(self, username, *, limit=20, cursor=None):
            # The pipeline reads each discovered account's own recent posts.
            return (
                [
                    {
                        "id": f"{username}-{i}",
                        "text": f"post {i} from {username}",
                        "authorUsername": username,
                        "impressionCount": 100 * i,
                        "createdAt": "2026-10-01T12:00:00+00:00",
                    }
                    for i in range(1, 4)
                ],
                None,
                False,
            )

        async def aclose(self):
            pass

    async def no_llm(_posts):
        return []

    monkeypatch.setattr("app.services.xpoz.XpozClient", FakeXpoz)
    monkeypatch.setattr("app.services.peer_pipeline.tag_posts", no_llm)
    monkeypatch.setattr(framework_corpus, "upsert_framework", lambda *a, **k: False)
    monkeypatch.setattr(framework_corpus, "upsert_peer_posts", lambda *a, **k: 0)
    monkeypatch.setattr("app.database.session_scope", _fake_session_scope)
    monkeypatch.setattr(listening, "session_scope", _fake_session_scope)

    result = await listening.discover_and_extract_niche_frameworks(
        profile_id=1, query="founder nigeria"
    )

    assert result["report_status"] == "insufficient_data", (
        "3-post accounts have no reliable baseline — an honest empty, never a guess"
    )
    assert result["qualifying_posts_count"] == 0
    remembered, origin, query = calls["remembered"][0]
    assert set(remembered) == {"peer_one", "peer_two"}, (
        "authors of non-qualifying posts are saved too — the search surfaced them"
    )
    assert origin == "niche" and query == "founder nigeria"
