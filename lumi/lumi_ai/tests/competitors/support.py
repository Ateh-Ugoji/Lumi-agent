"""In-memory stand-ins for the competitor pipeline's ports (tests only)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from lumi_ai.ports import (
    FrameworkOut,
    NicheReportIn,
    NicheReportOut,
    PeerPostOut,
    PostIn,
    PostMetrics,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def make_posts(
    handle: str, n: int = 40, *, winners: int = 8, views: int = 1000
) -> list[PostIn]:
    """``n`` mature posts of ~``views`` views; the first ``winners`` get 5x."""
    out = []
    for i in range(n):
        out.append(
            PostIn(
                platform="x",
                external_id=f"{handle}-{i}",
                text=f"{handle} post {i}\nsecond line",
                published_at=NOW - timedelta(days=2, hours=i * 12 % 600),
                author_handle=handle,
                kind="original",
                url=f"https://x.com/{handle}/status/{i}",
                metrics=PostMetrics(
                    views=views * 5 + i if i < winners else views + i,
                    likes=30,
                    comments=3,
                    shares=2,
                ),
            )
        )
    return out


class FakeSocial:
    def __init__(self, posts: dict[str, list[PostIn]] | None = None, errors=None):
        self.posts = posts or {}
        self.errors = errors or {}
        self.calls: list[tuple] = []

    async def fetch_user_posts(self, platform, handle, since, limit):
        self.calls.append((platform, handle, since, limit))
        err = self.errors.get(handle) or self.errors.get("*")
        if err:
            raise err
        return list(self.posts.get(handle, []))[:limit]

    async def search_posts(self, platform, query, limit):
        self.calls.append(("search", platform, query, limit))
        err = self.errors.get("search")
        if err:
            raise err
        return list(self.posts.get("search", []))[:limit]

    async def get_user(self, platform, handle):
        return None

    async def search_users(self, platform, query, limit):
        return []


class FakeReports:
    def __init__(self):
        self.reports: list[NicheReportOut] = []
        self.tag_rows: dict[tuple[str, str], object] = {}
        self.frameworks: list[FrameworkOut] = []
        self.order: list[str] = []

    async def save_report(self, profile_id, report: NicheReportIn):
        self.order.append("report")
        rid = len(self.reports) + 1
        fws = tuple(
            FrameworkOut(
                id=len(self.frameworks) + i + 1,
                profile_id=profile_id,
                report_id=rid,
                name=f.name,
                title=f.title,
                description=f.description,
                evidence_post_refs=f.evidence_post_refs,
                lift=f.lift,
                confidence=f.confidence,
                payload=f.payload,
            )
            for i, f in enumerate(report.frameworks)
        )
        self.frameworks.extend(fws)
        out = NicheReportOut(
            id=rid,
            profile_id=profile_id,
            niche_key=report.niche_key,
            status=report.status,
            posts_analyzed=report.posts_analyzed,
            winner_count=report.winner_count,
            payload=json.loads(json.dumps(report.payload)),
            frameworks=fws,
            detail=report.detail,
            created_at=NOW,
            query=report.query,
            peers_analyzed=report.peers_analyzed,
        )
        self.reports.append(out)
        self.last_in = report
        return out

    async def latest_report(self, profile_id):
        rows = [r for r in self.reports if r.profile_id == profile_id]
        return rows[-1] if rows else None

    async def get_frameworks(self, ids):
        return [f for f in self.frameworks if f.id in set(ids)]

    async def list_frameworks(self, profile_id, *, limit=100):
        return [f for f in reversed(self.frameworks) if f.profile_id == profile_id][
            :limit
        ]

    async def save_taggings(self, profile_id, taggings):
        for t in taggings:
            self.tag_rows[(t.post_ref, t.prompt_version)] = t
        return len(taggings)

    async def cached_taggings(self, profile_id, post_refs, prompt_version):
        return [
            self.tag_rows[(r, prompt_version)]
            for r in post_refs
            if (r, prompt_version) in self.tag_rows
        ]


class FakePeerStore:
    def __init__(self, reports: FakeReports | None = None):
        self.rows: dict[tuple[str, str], PeerPostOut] = {}
        self.reports = reports

    async def save_peer_posts(self, profile_id, posts):
        if self.reports is not None:
            self.reports.order.append("peer_posts")
        out = []
        for p in posts:
            key = (p.platform, p.external_id)
            prev = self.rows.get(key)
            row = PeerPostOut(
                id=prev.id if prev else len(self.rows) + 1,
                profile_id=profile_id,
                platform=p.platform,
                external_id=p.external_id,
                author_handle=p.author_handle,
                text=p.text,
                published_at=p.published_at,
                url=p.url,
                metrics=p.metrics,
                media=p.media,
                niche_key=p.niche_key,
            )
            self.rows[key] = replace(row)
            out.append(row)
        return out

    async def get_peer_posts(self, ids):
        return [r for r in self.rows.values() if r.id in set(ids)]

    async def list_peer_posts(self, profile_id, *, niche_key=None, limit=200):
        rows = [r for r in self.rows.values() if r.profile_id == profile_id]
        if niche_key:
            rows = [r for r in rows if r.niche_key == niche_key]
        return rows[:limit]


class TaggerLLM:
    """A ``Completer`` that answers every tagging batch for the posts it was shown.

    ``pas_ids`` get the PAS framework, the rest ``hot_take``; ``broken`` makes it reply with junk.
    """

    def __init__(self, pas_ids=(), *, broken: bool = False):
        from lumi_ai.tests.agent.harness import FakeLLM, say
        from lumi_ai.tests.competitors.test_extract import _analysis_json, _payload

        self._fake = FakeLLM
        self._say = say
        self._analysis = _analysis_json
        self._payload = _payload
        self.pas_ids = set(pas_ids)
        self.broken = broken
        self.batches: list[list[str]] = []

    async def complete(
        self, messages, tools=None, *, model=None, tier=None, effort=None
    ):
        ids = [p["post_id"] for p in json.loads(messages[-1]["content"])["posts"]]
        self.batches.append(ids)
        reply = (
            "sorry, I cannot do that"
            if self.broken
            else self._payload(
                *(
                    self._analysis(i, "pas" if i in self.pas_ids else "hot_take")
                    for i in ids
                )
            )
        )
        return await self._fake([self._say(reply)]).complete(
            messages, tools, model=model, tier=tier, effort=effort
        )

    @property
    def calls(self) -> int:
        return len(self.batches)
