"""The ORM stores keep the contract of ``lumi_ai.ports`` against a real PostgreSQL.

The ports are async; ``async_to_sync`` runs their ``thread_sensitive`` ORM calls on the test's own
thread so they share its transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from asgiref.sync import async_to_sync

from apps.intelligence import models as m
from apps.intelligence.repos import (
    ChatRepo,
    EvalRepo,
    ListeningRepo,
    MatchRepo,
    MemoryRepo,
    PeerPostRepo,
    PostRepo,
    ProfileRepo,
    ReportRepo,
    RepurposeRepo,
    RequestRepo,
    TurnLogRepo,
    VoiceRepo,
)
from apps.profiles import services
from lumi_ai import ports
from lumi_ai.ports import (
    AttemptIn,
    ChatMessageIn,
    EvaluationIn,
    EvaluationRecord,
    FrameworkIn,
    ListeningConfig,
    NicheIn,
    NicheReportIn,
    PeerPostIn,
    PostMetrics,
    StyleAnswerIn,
    TaggingRecord,
    TurnRecord,
)

pytestmark = pytest.mark.django_db

WHEN = datetime(2026, 10, 1, 12, tzinfo=UTC)


def call(fn, *args, **kwargs):
    return async_to_sync(fn)(*args, **kwargs)


def peer(external_id="p1", author="rival", text="a peer post", likes=40):
    return PeerPostIn(
        platform="x",
        external_id=external_id,
        author_handle=author,
        text=text,
        published_at=WHEN,
        metrics=PostMetrics(likes=likes),
    )


def test_every_repo_satisfies_its_port():
    pairs = [
        (ProfileRepo, ports.ProfileStore),
        (PostRepo, ports.PostStore),
        (PeerPostRepo, ports.PeerPostStore),
        (VoiceRepo, ports.VoiceStore),
        (ReportRepo, ports.ReportStore),
        (MemoryRepo, ports.MemoryStore),
        (ChatRepo, ports.ChatStore),
        (TurnLogRepo, ports.TurnLogStore),
        (RepurposeRepo, ports.RepurposeStore),
        (RequestRepo, ports.RequestStore),
        (ListeningRepo, ports.ListeningStore),
        (MatchRepo, ports.MatchStore),
        (EvalRepo, ports.EvalStore),
    ]
    for repo, port in pairs:
        assert isinstance(repo(), port), repo.__name__


class TestNiche:
    def test_the_profile_has_no_niche_until_one_is_saved(self, profile):
        assert call(ProfileRepo().get_niche, profile.pk) is None

    def test_save_replaces_keywords_and_handles_and_keeps_one_active_niche(
        self, profile
    ):
        repo = ProfileRepo()
        first = NicheIn(
            "ai:global",
            "AI builders",
            keywords=("llm", "LLM", "agents"),
            tracked_handles={"x": ("@Rival", "other")},
        )
        saved = call(repo.save_niche, profile.pk, first)
        assert saved.keywords == ("llm", "agents")  # case-insensitive duplicate dropped
        assert saved.tracked_handles == {"x": ("rival", "other")}

        call(repo.save_niche, profile.pk, NicheIn("cooking:global", "Cooking"))
        assert call(repo.get_niche, profile.pk).niche_key == "cooking:global"
        active = m.NichePreference.objects.filter(profile=profile, is_active=True)
        assert [n.niche_key for n in active] == ["cooking:global"]

        again = call(
            repo.save_niche, profile.pk, NicheIn("ai:global", "AI", keywords=("rag",))
        )
        assert again.keywords == ("rag",) and again.tracked_handles == {}
        assert m.NichePreference.objects.filter(profile=profile).count() == 2

    def test_the_profile_comes_from_the_service(self, profile):
        info = call(ProfileRepo().get_profile, profile.pk)
        assert info.id == profile.pk and info.primary_platform == "x"
        assert call(ProfileRepo().get_profile, 999999) is None


class TestPeerPosts:
    def test_saved_posts_are_stored_under_the_author_and_never_as_own_posts(
        self, profile
    ):
        repo = PeerPostRepo()
        saved = call(
            repo.save_peer_posts, profile.pk, [peer("p1"), peer("p2", "other")]
        )
        assert {p.author_handle for p in saved} == {"rival", "other"}
        assert all(p.metrics.likes == 40 and p.profile_id == profile.pk for p in saved)
        assert call(PostRepo().list_posts, profile.pk) == []  # not the profile's own

    def test_saving_twice_is_idempotent(self, profile):
        repo = PeerPostRepo()
        call(repo.save_peer_posts, profile.pk, [peer("p1")])
        again = call(repo.save_peer_posts, profile.pk, [peer("p1", text="edited")])
        assert len(again) == 1 and again[0].text == "edited"

    def test_get_by_id_keeps_the_order_asked(self, profile):
        saved = call(PeerPostRepo().save_peer_posts, profile.pk, [peer("a"), peer("b")])
        ids = [saved[1].id, saved[0].id]
        got = call(PeerPostRepo().get_peer_posts, ids)
        assert [p.id for p in got] == ids and got[0].profile_id == 0

    def test_list_follows_the_niche_handles_and_the_report_peers(self, profile):
        repo = PeerPostRepo()
        call(
            repo.save_peer_posts,
            profile.pk,
            [peer("a", "tracked"), peer("b", "stranger")],
        )
        assert call(repo.list_peer_posts, profile.pk) == []
        call(
            ProfileRepo().save_niche,
            profile.pk,
            NicheIn("ai:global", "AI", tracked_handles={"x": ("tracked",)}),
        )
        listed = call(repo.list_peer_posts, profile.pk)
        assert [p.author_handle for p in listed] == ["tracked"]
        assert call(repo.list_peer_posts, profile.pk, niche_key="other:key") == []


class TestVoice:
    def test_versions_grow_and_only_the_last_is_current(self, profile):
        repo = VoiceRepo()
        post = call(PeerPostRepo().save_peer_posts, profile.pk, [peer("v1")])[0]
        v1 = call(
            repo.save_voice,
            profile.pk,
            None,
            {"tone": "dry"},
            "posts",
            [post.id, post.id],
        )
        v2 = call(
            repo.save_voice,
            profile.pk,
            None,
            {"tone": "warm"},
            "questions",
            [],
            model="m",
            prompt_version="v2",
        )
        assert (v1.version, v2.version) == (1, 2)
        assert v1.example_post_ids == (post.id,)  # repeated example stored once
        current = call(repo.current_voice, profile.pk)
        assert current.version == 2 and current.platform is None
        assert m.VoiceProfile.objects.get(pk=v2.id).model == "m"
        assert call(repo.current_voice, profile.pk, "x") is None

    def test_platform_voices_are_independent(self, profile):
        repo = VoiceRepo()
        call(repo.save_voice, profile.pk, None, {"a": 1}, "posts", [])
        x = call(repo.save_voice, profile.pk, "x", {"a": 2}, "posts", [])
        assert x.version == 1 and x.platform == "x"
        assert call(repo.current_voice, profile.pk).version == 1

    def test_style_answers_are_upserted_by_question(self, profile):
        repo = VoiceRepo()
        call(repo.save_style_answers, profile.pk, [StyleAnswerIn("tone", "dry")])
        call(
            repo.save_style_answers,
            profile.pk,
            [StyleAnswerIn("tone", "warm"), StyleAnswerIn("emoji", "no")],
        )
        assert call(repo.list_style_answers, profile.pk) == [
            StyleAnswerIn("tone", "warm"),
            StyleAnswerIn("emoji", "no"),
        ]


class TestReports:
    def make(self, profile, **overrides):
        posts = call(
            PeerPostRepo().save_peer_posts, profile.pk, [peer("w1"), peer("w2")]
        )
        fields = {
            "niche_key": "ai:global",
            "status": "ok",
            "posts_analyzed": 2,
            "winner_count": 2,
            "payload": {"summary": "x"},
            "frameworks": (
                FrameworkIn(
                    name="pas",
                    title="Problem, agitate, solve",
                    description="d",
                    evidence_post_refs=("x:w1", "x:w2", "x:missing"),
                    lift=2.5,
                    confidence=0.8,
                    payload={"steps": 3},
                ),
            ),
            "query": "ai agents",
            "peers_analyzed": 1,
            "peer_handles": {"x": ("rival",)},
        }
        fields.update(overrides)
        return call(
            ReportRepo().save_report, profile.pk, NicheReportIn(**fields)
        ), posts

    def test_a_report_round_trips_with_frameworks_evidence_and_peers(self, profile):
        saved, _ = self.make(profile)
        assert saved.niche_key == "ai:global" and saved.peers_analyzed == 1
        (fw,) = saved.frameworks
        assert (fw.name, fw.title) == ("pas", "Problem, agitate, solve")
        assert fw.evidence_post_refs == (
            "x:w1",
            "x:w2",
        )  # the unstored ref is not invented
        assert fw.payload["steps"] == 3 and fw.lift == 2.5
        assert m.NicheReportPeer.objects.filter(report_id=saved.id).count() == 1
        latest = call(ReportRepo().latest_report, profile.pk)
        assert latest == saved

    def test_the_failure_reason_survives_and_stays_out_of_the_payload(self, profile):
        saved, _ = self.make(
            profile, status="insufficient_data", frameworks=(), detail="only 1 winner"
        )
        assert saved.detail == "only 1 winner" and saved.payload == {"summary": "x"}

    def test_frameworks_by_id_and_by_profile(self, profile):
        saved, _ = self.make(profile)
        repo = ReportRepo()
        fw = saved.frameworks[0]
        assert call(repo.get_frameworks, [fw.id, 99999]) == [fw]
        assert call(repo.list_frameworks, profile.pk) == [fw]

    def test_taggings_are_cached_per_prompt_version(self, profile):
        self.make(profile)
        repo = ReportRepo()
        tag = TaggingRecord("x:w1", "rival", "v1", "ok", {"hook": "q"}, "pas")
        failed = TaggingRecord("x:w2", "rival", "v1", "failed", None, None, "bad json")
        assert call(repo.save_taggings, profile.pk, [tag, failed]) == 2
        assert (
            call(repo.save_taggings, profile.pk, [tag]) == 1
        )  # upsert, not a second row
        got = call(repo.cached_taggings, profile.pk, ["x:w1", "x:w2", "x:nope"], "v1")
        assert {t.post_ref: t.status for t in got} == {"x:w1": "ok", "x:w2": "failed"}
        assert (
            next(t for t in got if t.post_ref == "x:w2").validation_error == "bad json"
        )
        assert call(repo.cached_taggings, profile.pk, ["x:w1"], "v2") == []


class TestMemory:
    def test_the_same_note_is_stored_once(self, profile):
        repo = MemoryRepo()
        first, created = call(repo.add_note, profile.pk, "Lives in Lima")
        again, created_again = call(repo.add_note, profile.pk, "  lives   in lima ")
        assert created and not created_again and again.id == first.id

    def test_touch_counts_reads_and_old_notes_are_deleted_by_last_read(self, profile):
        repo = MemoryRepo()
        old, _ = call(repo.add_note, profile.pk, "old")
        kept, _ = call(repo.add_note, profile.pk, "kept")
        m.MemoryNote.objects.filter(pk=old.id).update(
            last_accessed_at=datetime.now(UTC) - timedelta(days=90)
        )
        call(repo.touch_notes, [kept.id])
        assert m.MemoryNote.objects.get(pk=kept.id).access_count == 1
        gone = call(
            repo.delete_notes_older_than,
            profile.pk,
            datetime.now(UTC) - timedelta(days=30),
        )
        assert gone == [old.id]
        assert [n.id for n in call(repo.list_notes, profile.pk)] == [kept.id]

    def test_summary_is_empty_then_replaced(self, profile):
        repo = MemoryRepo()
        assert call(repo.get_summary, profile.pk) == ""
        call(repo.set_summary, profile.pk, "one")
        call(repo.set_summary, profile.pk, "two")
        assert call(repo.get_summary, profile.pk) == "two"


class TestRepurpose:
    def attempts(self):
        return [
            AttemptIn(
                "x", "draft 1", 1, True, tier="large", model="m", provider="groq"
            ),
            AttemptIn(
                "x",
                "draft 2",
                2,
                True,
                judge_verdict="yes",
                judge_confidence=0.9,
                is_fallback=True,
            ),
            AttemptIn("linkedin", "post", 1, False),
        ]

    def test_request_and_attempts_are_written_together(self, profile):
        repo = RepurposeRepo()
        request_id, out = call(
            repo.create_request_with_attempts,
            profile.pk,
            "source",
            "easy",
            self.attempts(),
        )
        assert [a.attempt_no for a in out] == [1, 2, 1] and out[0].created_at
        assert all(a.request_id == request_id for a in out)
        row = m.RepurposeRequest.objects.get(pk=request_id)
        assert (row.mode, row.brief, row.source_post_id) == ("repurpose", None, None)
        assert m.RepurposeAttempt.objects.get(pk=out[1].id).is_fallback is True

    def test_a_bad_attempt_leaves_no_orphan_request(self, profile):
        bad = [
            *self.attempts(),
            AttemptIn("x", "dup", 1, True),
        ]  # (request, x, 1) twice
        with pytest.raises(Exception, match="uq_repurpose_attempts_no|duplicate"):
            call(
                RepurposeRepo().create_request_with_attempts, profile.pk, "s", None, bad
            )
        assert m.RepurposeRequest.objects.count() == 0

    def test_the_source_post_must_be_the_profiles_own(
        self, profile, owner, make_profile
    ):
        mine = services.upsert_posts(
            profile.handle_id,
            [ports.PostIn("x", "m1", "mine", WHEN)],
        ).post_ids[0]
        theirs = call(PeerPostRepo().save_peer_posts, profile.pk, [peer("t1")])[0].id
        repo = RepurposeRepo()
        request_id, _ = call(
            repo.create_request_with_attempts,
            profile.pk,
            "mine",
            None,
            self.attempts()[:1],
            mode="topic",
            brief="be short",
            source_post_id=mine,
        )
        row = m.RepurposeRequest.objects.get(pk=request_id)
        assert (row.source_post_id, row.mode, row.brief) == (mine, "topic", "be short")
        with pytest.raises(LookupError):
            call(
                repo.create_request_with_attempts,
                profile.pk,
                "x",
                None,
                [],
                source_post_id=theirs,
            )
        other = make_profile(owner, "second")
        with pytest.raises(LookupError):
            call(
                repo.create_request_with_attempts,
                other.pk,
                "x",
                None,
                [],
                source_post_id=mine,
            )

    def test_user_actions_check_ownership_and_the_edit_rule(
        self, profile, owner, make_profile
    ):
        repo = RepurposeRepo()
        _, (first, *_) = call(
            repo.create_request_with_attempts, profile.pk, "s", None, self.attempts()
        )
        call(repo.record_user_action, profile.pk, first.id, "accept")
        call(repo.record_user_action, profile.pk, first.id, "edit", "better")
        call(repo.record_user_action, profile.pk, first.id, "reject", "ignored")
        kinds = list(
            m.UserAction.objects.order_by("id").values_list("action", "edited_text")
        )
        assert kinds == [("accept", None), ("edit", "better"), ("reject", None)]
        with pytest.raises(ValueError):
            call(repo.record_user_action, profile.pk, first.id, "edit", None)
        stranger = make_profile(owner, "second")
        with pytest.raises(LookupError):
            call(repo.record_user_action, stranger.pk, first.id, "accept")


class TestEvaluations:
    def record(self, profile, attempt_id, **kw):
        return EvaluationRecord(
            profile_id=profile.pk,
            platform="x",
            draft="draft 1",
            decision="regenerate",
            scores={"voice": 0.4},
            reasons={"voice": "too formal"},
            deterministic_failures=("em_dash",),
            style_similarity=0.42,
            judge="jev",
            config_version="q1",
            attempt_id=attempt_id,
            **kw,
        )

    def test_an_evaluation_round_trips_through_the_attempt(self, profile):
        _, (attempt, *_) = call(
            RepurposeRepo().create_request_with_attempts,
            profile.pk,
            "s",
            None,
            [AttemptIn("x", "draft 1", 1, True)],
        )
        repo = EvalRepo()
        saved_id = call(repo.save_evaluation, self.record(profile, attempt.id))
        row = m.GenerationEvaluation.objects.get(pk=saved_id)
        assert (row.attempt_id, row.style_score, row.decision) == (
            attempt.id,
            0.42,
            "regenerate",
        )
        assert call(repo.list_evaluations, profile.pk) == [
            self.record(profile, attempt.id)
        ]

    def evaluation_in(self, profile, draft="draft 1"):
        return EvaluationIn(
            profile_id=profile.pk,
            platform="x",
            draft=draft,
            decision="pass",
            scores={"voice": 0.9},
            reasons={},
            style_similarity=0.8,
            judge="jev",
        )

    def test_evaluations_are_stored_with_their_attempts_in_one_transaction(
        self, profile
    ):
        attempts = [AttemptIn("x", "a", 1, True), AttemptIn("x", "b", 2, True)]
        _, out = call(
            RepurposeRepo().create_request_with_attempts,
            profile.pk,
            "s",
            None,
            attempts,
            evaluations={
                1: self.evaluation_in(profile),
                2: self.evaluation_in(profile, "b"),
            },
        )
        rows = m.GenerationEvaluation.objects.order_by("attempt__attempt_no")
        assert [r.attempt_id for r in rows] == [o.id for o in out]
        assert [e.draft for e in call(EvalRepo().list_evaluations, profile.pk)] == [
            "b",
            "a",
        ]

    def test_a_failing_evaluation_leaves_neither_request_nor_attempts(self, profile):
        broken = self.evaluation_in(profile)
        object.__setattr__(broken, "decision", "x" * 100)  # does not fit the column
        with pytest.raises(Exception):  # noqa: B017 - any database error will do
            call(
                RepurposeRepo().create_request_with_attempts,
                profile.pk,
                "s",
                None,
                [AttemptIn("x", "a", 1, True)],
                evaluations={1: broken},
            )
        assert m.RepurposeRequest.objects.count() == 0
        assert m.RepurposeAttempt.objects.count() == 0

    def test_an_evaluation_for_an_attempt_that_does_not_exist_is_refused(self, profile):
        with pytest.raises(ValueError, match="unknown attempts"):
            call(
                RepurposeRepo().create_request_with_attempts,
                profile.pk,
                "s",
                None,
                [AttemptIn("x", "a", 1, True)],
                evaluations={2: self.evaluation_in(profile)},
            )
        assert m.RepurposeRequest.objects.count() == 0

    def test_an_attempt_of_another_profile_is_refused(
        self, profile, owner, make_profile
    ):
        _, (attempt, *_) = call(
            RepurposeRepo().create_request_with_attempts,
            profile.pk,
            "s",
            None,
            [AttemptIn("x", "draft 1", 1, True)],
        )
        stranger = make_profile(owner, "second")
        with pytest.raises(LookupError):
            call(EvalRepo().save_evaluation, self.record(stranger, attempt.id))


class TestUserRequests:
    def test_the_platform_defaults_to_the_profiles_and_repeats_are_flagged(
        self, profile
    ):
        repo = RequestRepo()
        first = call(repo.save_user_request, profile.pk, "@Someone", "look at them")
        second = call(repo.save_user_request, profile.pk, "someone", None)
        other = call(
            repo.save_user_request, profile.pk, "pro", None, platform="linkedin"
        )
        assert (first.handle, first.already_requested, first.note) == (
            "someone",
            False,
            "look at them",
        )
        assert second.already_requested is True and second.note is None
        assert other.handle == "pro"
        assert (
            m.UserSearchRequest.objects.get(pk=other.id).handle.platform == "linkedin"
        )
        listed = call(repo.list_user_requests, profile.pk)
        assert [(r.handle, r.already_requested) for r in listed] == [
            ("pro", False),
            ("someone", True),
            ("someone", False),
        ]


class TestTurnLog:
    def test_a_turn_is_recorded_and_can_be_marked_corrected(self, profile):
        repo = TurnLogRepo()
        message_id = call(ChatRepo().append, profile.pk, ChatMessageIn("user", "hola"))
        record = TurnRecord(
            profile_id=profile.pk,
            message_id=message_id,
            message_text_hash="h" * 64,
            message_preview="hola" * 80,
            rule_class="other",
            rule_matched=None,
            final_class="chitchat",
            path_taken="fast",
            tools_called=("get_analytics",),
            judge_called=True,
            judge_class="chitchat",
            judge_probs=({"label": "chitchat", "p": 0.9},),
            judge_confidence=0.9,
            total_latency_ms=120,
            timings={"llm_ms": 80},
        )
        row_id = call(repo.record_turn, record)
        row = m.TurnClassification.objects.get(pk=row_id)
        assert len(row.message_preview) == 160 and row.tools_called == ["get_analytics"]
        assert (row.jev_called, row.jev_confidence, row.credits_spent) == (
            True,
            0.9,
            None,
        )
        assert row.user_corrected is None
        call(repo.mark_corrected, row_id)
        row.refresh_from_db()
        assert row.user_corrected is True


class TestDelegations:
    def test_chat_history_round_trips(self, profile):
        repo = ChatRepo()
        call(repo.append, profile.pk, ChatMessageIn("user", "hi"))
        call(
            repo.append,
            profile.pk,
            ChatMessageIn("assistant", "hello", tools_used=("t",)),
        )
        history = call(repo.history, profile.pk, 10)
        assert [(h.role, h.content) for h in history] == [
            ("user", "hi"),
            ("assistant", "hello"),
        ]
        assert history[1].tools_used == ("t",)

    def test_listening_config_and_alerts(self, profile):
        repo = ListeningRepo()
        assert call(repo.get_listening, profile.pk).enabled is False
        saved = call(
            repo.set_listening, ListeningConfig(profile.pk, ("ai", "rag"), True, 30)
        )
        assert saved.keywords == ("ai", "rag") and saved.enabled
        assert call(repo.unread_alerts, profile.pk) == []
        assert call(repo.dismiss_alert, profile.pk, 12345) is False

    def test_a_listening_match_is_linked_once(self, profile):
        post = call(PeerPostRepo().save_peer_posts, profile.pk, [peer("m1")])[0]
        repo = MatchRepo()
        assert call(repo.record_listening_match, profile.pk, post.id, 0.9) is True
        assert call(repo.record_listening_match, profile.pk, post.id) is False
