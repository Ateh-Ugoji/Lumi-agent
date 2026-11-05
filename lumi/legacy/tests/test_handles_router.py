"""Tests for app/routers/handles.py — the main-app shim over the handle-search MVP.

No network, no credits: delegation is monkeypatched at the MVP module boundary
(the routes call `handle_core.api_*` attribute-style, so patches land), plus one
real hermetic call down the min-length guard (returns before any db/cache/Xpoz I/O).
"""

from fastapi.responses import JSONResponse

from app.routers import handles as handles_router
from mvp.handle_search import server as handle_core


def test_router_exposes_the_four_routes():
    paths = sorted(route.path for route in handles_router.router.routes)
    assert paths == [
        "/handles/saved",
        "/handles/search",
        "/handles/select",
        "/handles/stats",
    ]


async def test_search_delegates_q_and_context(monkeypatch):
    seen: dict = {}

    async def fake_api_search(q: str = "", context: str = "",
                              platforms: str = "x") -> dict:
        seen["q"] = q
        seen["context"] = context
        seen["platforms"] = platforms
        return {"query": q, "results": [], "reason": "ok"}

    monkeypatch.setattr(handle_core, "api_search", fake_api_search)

    result = await handles_router.search_handles(
        q="kar", context="founder openai", platforms="x,instagram")

    assert seen == {"q": "kar", "context": "founder openai",
                    "platforms": "x,instagram"}
    assert result["reason"] == "ok"


async def test_search_min_length_is_hermetic():
    # Real core path: the min-length guard returns before db/cache/Xpoz I/O.
    result = await handles_router.search_handles(q="a")
    assert result["reason"] == "min_length"
    assert result["results"] == []


async def test_saved_delegates(monkeypatch):
    seen: dict = {}

    async def fake_api_saved(platforms: str = "x") -> dict:
        seen["platforms"] = platforms
        return {"results": [{"handle": "AtehOfficial", "source": "db"}], "count": 1}

    monkeypatch.setattr(handle_core, "api_saved", fake_api_saved)

    result = await handles_router.list_saved_handles(platforms="x,reddit")
    assert seen == {"platforms": "x,reddit"}
    assert result["count"] == 1
    assert result["results"][0]["handle"] == "AtehOfficial"


async def test_select_delegates_the_body(monkeypatch):
    seen: dict = {}

    async def fake_api_select(item) -> dict:
        seen.update(item.model_dump())
        return {"remembered": True, "handle": item.handle.lower()}

    monkeypatch.setattr(handle_core, "api_select", fake_api_select)

    body = handle_core.SelectHandle(handle="Karpathy", followers=100)
    result = await handles_router.select_handle(body)

    assert seen["handle"] == "Karpathy"
    assert seen["followers"] == 100
    assert result == {"remembered": True, "handle": "karpathy"}


async def test_stats_passes_the_json_response_through(monkeypatch):
    async def fake_api_stats() -> JSONResponse:
        return JSONResponse({"live_budget": 10, "saved_handles": 42})

    monkeypatch.setattr(handle_core, "api_stats", fake_api_stats)

    response = await handles_router.get_handle_stats()
    assert isinstance(response, JSONResponse)
    assert response.body  # passthrough, not re-wrapped


async def test_main_app_registers_the_router():
    import app.main  # import-only: lifespan does not run without a TestClient

    prefixes: set[str] = set()
    for route in app.main.app.routes:
        if type(route).__name__ == "_IncludedRouter":
            # newer FastAPI wraps included routers instead of flattening
            router = getattr(route, "original_router", None)
            prefixes.add((getattr(router, "prefix", "") or "").strip("/"))
        elif getattr(route, "path", "").startswith("/"):
            prefixes.add(route.path.split("/")[1])
    assert "handles" in prefixes
