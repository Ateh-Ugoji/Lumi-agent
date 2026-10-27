import pytest

from lumi_ai.config import AIConfig
from lumi_ai.video.codec import PROMPT_VERSION
from lumi_ai.video.fake import FakeVideoAnalyzer, InMemoryVideoStore, sample_analysis
from lumi_ai.video.service import analyze_videos, persist

URLS = [f"https://cdn.example.com/{i}.mp4" for i in range(4)]


async def _run(urls, analyzer, store=None, **config):
    return await analyze_videos(
        urls, analyzer, store=store, config=AIConfig(**config), provider="fake"
    )


async def test_analyses_every_url_once() -> None:
    analyzer = FakeVideoAnalyzer()
    batch = await _run(URLS[:2] + URLS[:1], analyzer)
    assert set(batch.results) == set(URLS[:2]) and len(analyzer.calls) == 2
    assert len(batch.fresh) == 2 and not batch.failures


async def test_cached_videos_cost_nothing() -> None:
    store = InMemoryVideoStore()
    await store.save([sample_analysis(URLS[0])], model="m")
    analyzer = FakeVideoAnalyzer()
    batch = await _run(URLS[:2], analyzer, store)
    assert [c[0] for c in analyzer.calls] == [URLS[1]]
    assert URLS[0] in batch.results and len(batch.fresh) == 1


async def test_a_new_prompt_version_is_not_a_cache_hit() -> None:
    store = InMemoryVideoStore()
    await store.save([sample_analysis(URLS[0], prompt_version="video-v0")], model="m")
    analyzer = FakeVideoAnalyzer()
    await _run(URLS[:1], analyzer, store)
    assert len(analyzer.calls) == 1


async def test_the_per_run_cap_skips_the_rest_and_says_so() -> None:
    analyzer = FakeVideoAnalyzer()
    batch = await _run(URLS, analyzer, video_max_per_run=2)
    assert len(analyzer.calls) == 2 and len(batch.skipped) == 2
    assert all("VIDEO_MAX_PER_RUN" in why for why in batch.skipped.values())
    assert len(batch.notes()) == 2


async def test_cache_hits_do_not_count_against_the_cap() -> None:
    store = InMemoryVideoStore()
    await store.save([sample_analysis(u) for u in URLS[:2]], model="m")
    analyzer = FakeVideoAnalyzer()
    batch = await _run(URLS, analyzer, store, video_max_per_run=2)
    assert len(analyzer.calls) == 2 and not batch.skipped and len(batch.results) == 4


async def test_one_failure_does_not_stop_the_others_and_keeps_its_reason() -> None:
    analyzer = FakeVideoAnalyzer(failing={URLS[0]: "gemini HTTP 429: quota"})
    batch = await _run(URLS[:3], analyzer)
    assert set(batch.results) == set(URLS[1:3])
    assert batch.failures == {URLS[0]: "gemini HTTP 429: quota"}
    assert "429" in batch.notes()[0]


async def test_an_unexpected_crash_is_a_failure_not_an_exception() -> None:
    class Boom:
        async def analyze(self, media_url, *, context=None):
            raise RuntimeError("secret detail")

    batch = await _run(URLS[:1], Boom())
    assert batch.failures[URLS[0]] == "unexpected error: RuntimeError"


async def test_persist_stores_successes_and_failures_but_never_replaces_a_success() -> (
    None
):
    store = InMemoryVideoStore()
    analyzer = FakeVideoAnalyzer(failing={URLS[1]: "nope"})
    batch = await _run(URLS[:2], analyzer, store)
    await persist(batch, store, provider="fake", model="m")
    assert (URLS[0], "fake", PROMPT_VERSION) in store.rows
    assert store.failures == {(URLS[1], "fake", PROMPT_VERSION): "nope"}
    assert not await store.save_failure(
        URLS[0], provider="fake", model="m", prompt_version=PROMPT_VERSION, error="late"
    )


async def test_contexts_reach_the_analyzer() -> None:
    analyzer = FakeVideoAnalyzer()
    await analyze_videos(
        URLS[:1],
        analyzer,
        store=None,
        config=AIConfig(),
        provider="fake",
        contexts={URLS[0]: "caption"},
    )
    assert analyzer.calls == [(URLS[0], "caption")]


@pytest.mark.parametrize("urls", [[]])
async def test_nothing_to_do_calls_nothing(urls) -> None:
    analyzer = FakeVideoAnalyzer()
    assert (await _run(urls, analyzer)).results == {} and not analyzer.calls
