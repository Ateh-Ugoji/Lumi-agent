"""T8: the INTELLIGENCE importers over a synthetic legacy database (frozen fixtures plus rows
of their own: the frozen rows of ARCHITECT cover no INTELLIGENCE table)."""

import sqlite3
from io import StringIO

import pytest
from django.core.management import call_command

from apps.chat.models import ChatMessage
from apps.core.models import LegacyImportMap
from apps.core.tests.legacy_db import build_legacy_db
from apps.intelligence.models import (
    NicheReport,
    PostTagging,
    ProfileMemorySummary,
    RepurposeAttempt,
    RepurposeRequest,
    StyleAnswer,
    TurnClassification,
    UserAction,
    UserSearchRequest,
    VoiceProfile,
    VoiceProfileExample,
)
from apps.profiles.models import Post, SocialHandle

pytestmark = pytest.mark.django_db

TS = "2026-02-01 10:00:00.000000"

ROWS = {
    "user_search_requests": [
        (1, 1, "@Levelsio", "quiero verlo", TS),
        (2, 3, "bad handle!!", None, TS),
        (3, 4, "sama", None, TS),
    ],
    "style_answers": [
        (1, 1, "tone", "first", TS),
        (2, 1, "tone", "second", TS),
        (3, 3, "tone", "from the merged profile", "2026-02-03 10:00:00.000000"),
        (4, 2, "goal", "grow", TS),
        (5, 4, "x", "z", TS),
    ],
    "voice_profiles": [
        (1, 1, 1, 0, '{"tone":"dry"}', "[10, 11, 99, 10]", TS),
        (2, 1, 2, 1, '{"tone":"dry2"}', "[12]", TS),
        (3, 3, 2, 1, '{"tone":"merged"}', "[]", TS),
        (4, 2, 1, 1, None, None, TS),
        (5, 4, 1, 1, "{}", "[]", TS),
    ],
    "own_post_analysis": [
        (1, 10, None, '{"a": 1}', "ok", TS),
        (2, 10, None, '{"a": 2}', "ok", TS),
        (3, 11, "v1", None, "pending", TS),
        (4, 14, "v1", None, "pending", TS),
        (5, 13, "v1", "{}", "weird", TS),
    ],
    "post_taggings": [
        (1, "p-1", "AtehOfficial", "ok", '{"k": 1}', "hook", None, "v1", TS),
        (2, "zz-1", "sama", "ok", '{"k": 2}', "story", None, "v1", TS),
        (3, "p-1", "atehofficial", "failed", None, None, "bad json", "v2", TS),
        (4, "q-1", "bad handle!!", "ok", None, None, None, "v1", TS),
        (5, "p-2", "atehofficial", "ok", '{"z": 1}', "x", None, "v1", TS),
    ],
    "peer_frameworks": [
        (1, 1, "growth", "Niche A", '{"f": [1]}', 4, TS),
        (2, 2, "q2", "t2", None, 0, TS),
    ],
    "niche_framework_reports": [
        (1, 1, "fitness", "ok", '{"x": 1}', 30, 3, TS),
        (2, 2, "cooking", "weird", None, -1, 0, TS),
    ],
    "repurpose_requests": [
        (1, 1, "caption", "HARD", TS),
        (2, 3, "caption 2", None, TS),
        (3, 4, "skipped", None, TS),
    ],
    "repurpose_attempts": [
        (1, 1, "x", "fast", "m", "groq", 1, "out", 1, "YES", 0.9, TS),
        (2, 1, "x", "fast", "m", "groq", 1, "again", 1, None, None, TS),
        (3, 1, "linkedin", None, None, None, 1, "li", 0, None, None, TS),
        (4, 2, "x", None, None, None, 1, "conf", 1, "no", 5.0, TS),
        (5, 3, "x", None, None, None, 1, "orphan", 1, None, None, TS),
        (6, 1, "myspace", None, None, None, 1, "bad", 1, None, None, TS),
    ],
    "user_actions": [
        (1, 1, "ACCEPT", None, TS),
        (2, 1, "edit", "edited", TS),
        (3, 3, "edit", None, TS),
        (4, 1, "reject", "kept text", TS),
        (5, 5, "accept", None, TS),
    ],
    "turn_classifications": [
        (1, 1, 1, TS, "h1", "hello", "chitchat", None, 0, None, None, None, None,
         None, "chitchat", "FAST", '["get_posts"]', None, 12, None, '{"jev": 3}'),
        (2, 1, 5, TS, "h2", "orphan msg", "other", None, 1, "x", '{"x": 0.9}', 0.9, 5,
         None, "x", "weird", "{}", 0.0, 9, 1, None),
        (3, 4, None, TS, "h3", "skip", "other", None, 0, None, None, None, None,
         None, "other", "full", None, None, None, None, None),
    ],
}  # fmt: skip


def table_sql(name, rows):
    return f'INSERT INTO "{name}" VALUES ({",".join("?" * len(rows[0]))})'


@pytest.fixture(autouse=True)
def encryption_key(settings):
    from cryptography.fernet import Fernet

    settings.TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = ""


@pytest.fixture
def legacy(tmp_path):
    path = build_legacy_db(tmp_path / "lumi.db")
    conn = sqlite3.connect(path)
    for name, rows in ROWS.items():
        conn.executemany(table_sql(name, rows), rows)
    conn.commit()
    conn.close()
    return path


def run(path, *args):
    out = StringIO()
    call_command("import_legacy", "--sqlite", str(path), *args, stdout=out)
    return out.getvalue()


def test_every_row_of_every_table_is_accounted_for_and_verify_passes(legacy):
    run(legacy)
    out = run(legacy, "--verify")
    for table, rows in ROWS.items():
        assert f"{table}: origen {len(rows)}, registradas {len(rows)}" in out
        assert (
            f"{table}: origen" in out
            and "difiere" not in out.split(table)[1].split("\n")[0]
        )


def row_counts():
    return {
        m.__name__: m.objects.count()
        for m in (
            UserSearchRequest, StyleAnswer, VoiceProfile, VoiceProfileExample, PostTagging,
            NicheReport, RepurposeRequest, RepurposeAttempt, UserAction,
            TurnClassification, Post, SocialHandle, LegacyImportMap,
        )
    }  # fmt: skip


def test_a_second_run_changes_nothing(legacy):
    run(legacy)
    before = row_counts()
    run(legacy)
    assert row_counts() == before


def test_search_requests_take_the_platform_of_the_profile_handle(legacy):
    run(legacy)
    (req,) = UserSearchRequest.objects.all()
    assert (req.handle.platform, req.handle.handle_normalized) == ("x", "levelsio")
    assert (
        req.handle.origin == "niche"
    )  # the match importer got there first; never lowered
    assert (req.profile_id, req.request_note) == (1, "quiero verlo")


def test_style_answers_keep_the_highest_id_and_report_the_rest(legacy):
    out = run(legacy)
    answers = {a.question_key: a for a in StyleAnswer.objects.all()}
    assert answers["tone"].answer == "from the merged profile"
    assert answers["tone"].updated_at == answers["tone"].created_at
    assert answers["goal"].answer == "grow"
    assert StyleAnswer.objects.count() == 2
    assert "style_answers 1" in out and "style_answers 2" in out
    merged = LegacyImportMap.objects.filter(
        source_table="style_answers", outcome="merged"
    )
    assert sorted(merged.values_list("source_pk", flat=True)) == ["1", "2"]
    assert all(m.payload for m in merged)


def test_voice_profiles_one_current_and_examples_without_orphans(legacy):
    out = run(legacy)
    v1, v2 = VoiceProfile.objects.filter(profile_id=1).order_by("version")
    assert (v1.platform, v1.source, v1.is_current) == ("x", "posts", False)
    assert (v2.is_current, v2.payload) == (True, {"tone": "dry2"})
    # post 99 does not exist and the second mention of post 10 is a repeat
    examples = list(v1.examples.order_by("position").values_list("position", "post_id"))
    assert [p for p, _ in examples] == [0, 1]
    assert [e.position for e in v2.examples.all()] == [0]
    assert v2.examples.get().post_id == v1.examples.order_by("position").first().post_id
    # row 3 (merged profile, same version) folded into row 2; row 4 had no payload
    assert VoiceProfile.objects.get(profile_id=2).payload == {}
    assert VoiceProfile.objects.count() == 3
    merged = LegacyImportMap.objects.get(source_table="voice_profiles", source_pk="3")
    assert merged.outcome == "merged" and merged.payload
    assert "voice_profiles 3" in out
    # rows kept in the map because the new tables hold less than they said
    for pk in ("1", "4"):
        assert LegacyImportMap.objects.get(
            source_table="voice_profiles", source_pk=pk
        ).payload


def test_taggings_resolve_posts_create_stubs_and_merge_duplicates(legacy):
    run(legacy)
    own = Post.objects.get(
        platform_post_id="p-1", author__handle_normalized="atehofficial"
    )
    assert own.is_stub is False
    # own_post_analysis rows 1 and 2 (same post, version '') became one, the newest
    plain = PostTagging.objects.get(post=own, prompt_version="")
    assert plain.analysis == {"a": 2}
    assert (
        PostTagging.objects.get(post=own, prompt_version="v1").framework_guess == "hook"
    )
    assert (
        PostTagging.objects.get(post=own, prompt_version="v2").validation_error
        == "bad json"
    )
    stub = Post.objects.get(platform_post_id="zz-1")
    assert stub.is_stub and stub.author.handle_normalized == "sama"
    assert stub.author.platform == "x"
    # tagging 5 collided with own_post_analysis 3 (post 11, 'v1') and folded into it
    second = Post.objects.get(platform_post_id="p-2")
    assert PostTagging.objects.filter(post=second, prompt_version="v1").count() == 1
    assert (
        LegacyImportMap.objects.get(source_table="post_taggings", source_pk="5").outcome
        == "merged"
    )
    # an unknown status is stored as failed and the row is kept
    odd = LegacyImportMap.objects.get(source_table="own_post_analysis", source_pk="5")
    assert odd.payload
    assert PostTagging.objects.filter(status="failed").count() == 2


def test_niche_reports_keep_the_raw_payload_and_say_so(legacy):
    out = run(legacy)
    peer = NicheReport.objects.get(origin="legacy_peer_frameworks", profile_id=1)
    assert (peer.query, peer.niche, peer.status, peer.peers_analyzed) == (
        "growth",
        "Niche A",
        "ok",
        4,
    )
    assert peer.report == {"f": [1]}
    niche = NicheReport.objects.get(origin="legacy_niche_report", profile_id=1)
    assert (niche.niche, niche.posts_analyzed, niche.winner_count) == ("fitness", 30, 3)
    broken = NicheReport.objects.get(origin="legacy_niche_report", profile_id=2)
    assert (broken.status, broken.posts_analyzed, broken.report) == ("failed", 0, {})
    assert (
        NicheReport.objects.get(origin="legacy_peer_frameworks", profile_id=2).status
        == "failed"
    )
    assert "payload crudo" in out


def test_repurpose_chain_requests_attempts_and_actions(legacy):
    run(legacy)
    assert RepurposeRequest.objects.count() == 2
    assert RepurposeRequest.objects.get(source_caption="caption").route_label == "hard"
    attempts = {
        (a.request.source_caption, a.platform): a
        for a in RepurposeAttempt.objects.all()
    }
    first = attempts[("caption", "x")]
    assert (first.output, first.judge_verdict, first.judge_confidence) == (
        "out",
        "yes",
        0.9,
    )
    assert first.is_fallback is False
    assert (
        attempts[("caption 2", "x")].judge_confidence is None
    )  # 5.0 is not a confidence
    assert RepurposeAttempt.objects.count() == 3
    assert (
        LegacyImportMap.objects.get(
            source_table="repurpose_attempts", source_pk="2"
        ).outcome
        == "merged"
    )
    actions = {(a.attempt_id, a.action): a for a in UserAction.objects.all()}
    assert (first.pk, "accept") in actions
    assert actions[(first.pk, "edit")].edited_text == "edited"
    assert actions[(first.pk, "reject")].edited_text is None
    assert UserAction.objects.count() == 3
    skipped = LegacyImportMap.objects.get(source_table="user_actions", source_pk="3")
    assert skipped.outcome == "skipped" and skipped.payload


def test_turn_classifications_link_messages_and_arrays(legacy):
    run(legacy)
    first, second = TurnClassification.objects.order_by("created_at", "pk")
    assert first.message_id == 1 and ChatMessage.objects.filter(pk=1).exists()
    assert (first.path_taken, first.tools_called, first.timings) == (
        "fast",
        ["get_posts"],
        {"jev": 3},
    )
    assert first.credits_spent is None
    assert second.message_id is None and second.path_taken is None
    assert second.jev_probs == {"x": 0.9} and second.user_corrected is True
    assert TurnClassification.objects.count() == 2
    assert LegacyImportMap.objects.get(
        source_table="turn_classifications", source_pk="2"
    ).payload


def test_memory_md_goes_to_the_first_imported_profile(legacy, tmp_path):
    memo = tmp_path / "memory.md"
    memo.write_text("# Lo que sé\n- escribe seco\n", encoding="utf-8")
    out = run(legacy, "--memory-md", str(memo))
    summary = ProfileMemorySummary.objects.get()
    assert summary.profile_id == 1 and "escribe seco" in summary.summary_md
    assert "el primero importado" in out


def test_memory_md_that_cannot_be_read_is_reported_not_fatal(legacy, tmp_path):
    out = run(legacy, "--memory-md", str(tmp_path / "missing.md"))
    assert "memory.md no se importó" in out
    assert ProfileMemorySummary.objects.count() == 0
