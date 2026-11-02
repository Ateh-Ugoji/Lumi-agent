"""Tests for active niche preferences and niche report ingestion endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.intelligence import models as m
from apps.profiles.models import MetricSnapshot, Post, SocialHandle

pytestmark = pytest.mark.urls("apps.intelligence.tests.urls")

PREF_URL = "/api/v1/intelligence/niche-preferences/active"
INGEST_URL = "/api/v1/intelligence/niche-reports/ingest"


class TestActiveNichePreferences:
    def test_default_preferences_returned_when_none_configured(self, api, profile):
        res = api.get(f"{PREF_URL}?profile_id={profile.pk}")
        assert res.status_code == 200, res.content
        data = res.json()
        assert data["profile_id"] == profile.pk
        assert data["email"] == profile.user.email
        assert len(data["keywords"]) > 0
        assert data["is_active"] is False

    def test_configured_preferences_returned(self, api, profile):
        pref = m.NichePreference.objects.create(
            profile=profile,
            niche_key="b2b-saas:global",
            title="B2B SaaS Growth",
            source=m.NicheSource.USER,
            is_active=True,
        )
        m.NichePreferenceKeyword.objects.create(preference=pref, keyword="saas growth")
        m.NichePreferenceKeyword.objects.create(preference=pref, keyword="cold outreach")

        handle_obj = SocialHandle.objects.create(
            platform="x",
            handle_normalized="sama",
            handle_display="@sama",
        )
        m.NichePreferenceHandle.objects.create(preference=pref, handle=handle_obj)

        res = api.get(f"{PREF_URL}?profile_id={profile.pk}")
        assert res.status_code == 200, res.content
        data = res.json()
        assert data["profile_id"] == profile.pk
        assert data["title"] == "B2B SaaS Growth"
        assert "saas growth" in data["keywords"]
        assert "cold outreach" in data["keywords"]
        assert "@sama" in data["handles"] or "sama" in data["handles"]
        assert data["is_active"] is True


class TestNicheReportIngest:
    def test_ingest_report_creates_models_and_evidence(self, api, profile):
        payload = {
            "profile_id": profile.pk,
            "niche": "AI Automation",
            "query": "ai agents OR automation",
            "origin": "pipeline",
            "posts_analyzed": 40,
            "winner_count": 2,
            "peers_analyzed": 5,
            "report": {"summary": "Strong traction for tool breakdowns"},
            "posts": [
                {
                    "platform_post_id": "tw_1001",
                    "platform": "x",
                    "author_handle": "automate_daily",
                    "author_display_name": "Automate Daily",
                    "caption": "How to build an AI agent in 10 minutes",
                    "url": "https://x.com/automate_daily/status/tw_1001",
                    "published_at": datetime(2026, 11, 1, 12, 0, tzinfo=UTC).isoformat(),
                    "likes": 350,
                    "comments": 45,
                    "reposts": 80,
                    "views": 15000,
                    "format": "thread",
                },
                {
                    "platform_post_id": "ig_2002",
                    "platform": "instagram",
                    "author_handle": "growth_reels",
                    "caption": "3 tools you need this week",
                    "url": "https://instagram.com/p/ig_2002",
                    "likes": 1200,
                    "comments": 90,
                },
            ],
            "frameworks": [
                {
                    "name": "Step-by-step Tutorial with Hook",
                    "description": "Walkthrough format with outcome-first promise",
                    "lift": 2.4,
                    "confidence": 0.92,
                    "ordinal": 0,
                    "payload": {
                        "hook_type": "how_to_promise",
                        "primary_framework": "tutorial",
                        "cta_type": "like_bookmark",
                    },
                    "evidence_platform_post_ids": ["tw_1001"],
                }
            ],
        }

        res = api.post(INGEST_URL, payload, format="json")
        assert res.status_code == 201, res.content
        data = res.json()
        assert data["ok"] is True
        assert data["frameworks_count"] == 1
        assert data["posts_saved"] == 2

        report = m.NicheReport.objects.get(pk=data["report_id"])
        assert report.profile == profile
        assert report.niche == "AI Automation"
        assert report.posts_analyzed == 40

        post = Post.objects.get(platform_post_id="tw_1001")
        assert post.author.handle_normalized == "automate_daily"
        assert post.author.platform == "x"
        assert post.url == "https://x.com/automate_daily/status/tw_1001"

        snapshot = MetricSnapshot.objects.filter(post=post).first()
        assert snapshot is not None
        assert snapshot.likes == 350
        assert snapshot.views == 15000

        fw = m.Framework.objects.get(report=report)
        assert fw.name == "Step-by-step Tutorial with Hook"
        assert fw.lift == 2.4

        evidence = m.FrameworkEvidence.objects.filter(framework=fw).first()
        assert evidence is not None
        assert evidence.post == post

    def test_unowned_profile_is_rejected(self, api):
        payload = {
            "profile_id": 999999,
            "niche": "Hacking",
            "query": "test",
        }
        res = api.post(INGEST_URL, payload, format="json")
        assert res.status_code == 404
