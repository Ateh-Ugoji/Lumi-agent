"""Competitor pipeline + video: off means unchanged, on adds the reading to blind tagging."""

import json
from dataclasses import replace

from lumi_ai.competitors.pipeline import run_peer_pipeline
from lumi_ai.config import AIConfig
from lumi_ai.ports import MediaRef
from lumi_ai.tests.competitors.support import (
    NOW,
    FakePeerStore,
    FakeReports,
    FakeSocial,
    TaggerLLM,
    make_posts,
)
from lumi_ai.tests.competitors.test_pipeline import HANDLES, _winner_ids
from lumi_ai.video.fake import FakeVideoAnalyzer, InMemoryVideoStore


class RecordingLLM(TaggerLLM):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.payloads: list[dict] = []
        self.systems: list[str] = []

    async def complete(self, messages, tools=None, **kw):
        self.payloads.append(json.loads(messages[-1]["content"]))
        self.systems.append(messages[0]["content"])
        return await super().complete(messages, tools, **kw)


def _vid(post):
    return replace(
        post,
        media=(
            MediaRef(kind=None, url=f"https://video.twimg.com/{post.external_id}.mp4"),
        ),
    )


def _posts(with_video=("alice-0", "alice-1", "bob-0")):
    return {
        h: [
            _vid(p) if p.external_id in with_video else p
            for p in make_posts(h, winners=5)
        ]
        for h in HANDLES
    }


def _deps(video=None, store=None, **config):
    from lumi_ai.competitors.pipeline import PipelineDeps

    reports = FakeReports()
    llm = RecordingLLM(pas_ids=_winner_ids())
    deps = PipelineDeps(
        social=FakeSocial(_posts()),
        llm=llm,
        reports=reports,
        peer_posts=FakePeerStore(reports),
        config=AIConfig(**config),
        video=video,
        video_store=store,
    )
    return deps, llm


async def _run(deps):
    return await run_peer_pipeline(
        deps,
        profile_id=1,
        platform="x",
        niche="ai tools",
        niche_key="ai-tools:global",
        handles=HANDLES,
        now=NOW,
    )


async def test_without_a_video_analyzer_the_pipeline_is_exactly_as_before() -> None:
    deps, llm = _deps()
    result = await _run(deps)
    assert result.report.status == "ok"
    assert result.video_analyzed == 0 and result.video_notes == []
    assert all("video" not in p for batch in llm.payloads for p in batch["posts"])
    assert all('"video" object' not in s for s in llm.systems)


async def test_the_video_reading_enters_blind_tagging_as_an_extra_field() -> None:
    analyzer = FakeVideoAnalyzer()
    deps, llm = _deps(analyzer, InMemoryVideoStore())
    result = await _run(deps)
    assert result.report.status == "ok" and result.video_analyzed == 3
    shown = {p["post_id"]: p for batch in llm.payloads for p in batch["posts"]}
    assert shown["alice-0"]["video"]["pace"] == "fast"
    assert "video" not in shown["carol-0"]
    blob = json.dumps(llm.payloads)
    assert "views" not in blob and "https://video.twimg.com" not in blob, (
        "tagging stays blind"
    )
    assert any('"video" object' in s for s in llm.systems)
    assert {url for url, _ in analyzer.calls} == {
        f"https://video.twimg.com/{i}.mp4" for i in ("alice-0", "alice-1", "bob-0")
    }


async def test_a_second_run_reuses_the_stored_analyses() -> None:
    store = InMemoryVideoStore()
    analyzer = FakeVideoAnalyzer()
    deps, _ = _deps(analyzer, store)
    await _run(deps)
    first = len(analyzer.calls)
    deps2, _ = _deps(analyzer, store)
    await _run(deps2)
    assert first == 3 and len(analyzer.calls) == first


async def test_a_failing_video_is_reported_and_the_run_still_succeeds() -> None:
    bad = "https://video.twimg.com/alice-1.mp4"
    deps, llm = _deps(
        FakeVideoAnalyzer(failing={bad: "gemini HTTP 429: quota"}), InMemoryVideoStore()
    )
    result = await _run(deps)
    assert result.report.status == "ok" and result.video_analyzed == 2
    assert any("429" in n for n in result.video_notes)
    shown = {p["post_id"]: p for batch in llm.payloads for p in batch["posts"]}
    assert "video" not in shown["alice-1"]


async def test_the_per_run_cap_is_reported_not_silent() -> None:
    deps, _ = _deps(FakeVideoAnalyzer(), InMemoryVideoStore(), video_max_per_run=1)
    result = await _run(deps)
    assert result.video_analyzed == 1
    assert len([n for n in result.video_notes if "VIDEO_MAX_PER_RUN" in n]) == 2


async def test_images_and_unknown_non_video_urls_are_never_sent() -> None:
    posts = make_posts("alice", winners=5)
    posts[0] = replace(
        posts[0],
        media=(
            MediaRef(kind="image", url="https://a/b.mp4"),
            MediaRef(kind=None, url="https://pbs.twimg.com/x.jpg"),
        ),
    )
    reports = FakeReports()
    from lumi_ai.competitors.pipeline import PipelineDeps

    analyzer = FakeVideoAnalyzer()
    deps = PipelineDeps(
        social=FakeSocial(
            {
                "alice": posts,
                "bob": make_posts("bob", winners=5),
                "carol": make_posts("carol", winners=5),
            }
        ),
        llm=RecordingLLM(pas_ids=_winner_ids()),
        reports=reports,
        peer_posts=FakePeerStore(reports),
        config=AIConfig(),
        video=analyzer,
    )
    await _run(deps)
    assert analyzer.calls == []
