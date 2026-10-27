import hashlib
import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from apps.accounts.models import User
from apps.chat.models import ChatMessage
from apps.core.legacy_import import LEGACY_TABLES
from apps.core.models import LegacyImportMap
from apps.profiles.models import (
    Alert,
    HandleSnapshot,
    ListeningMatch,
    MetricSnapshot,
    PollConfig,
    Post,
    ProfileBaseline,
    SocialHandle,
    SocialProfile,
)

from .legacy_db import build_legacy_db

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def encryption_key(settings):
    from cryptography.fernet import Fernet

    settings.TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = ""


@pytest.fixture
def legacy(tmp_path):
    return build_legacy_db(tmp_path / "lumi.db")


def run(path, *args):
    out = StringIO()
    call_command("import_legacy", "--sqlite", str(path), *args, stdout=out)
    return out.getvalue()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def counts():
    return {
        m.__name__: m.objects.count()
        for m in (
            SocialProfile, SocialHandle, HandleSnapshot, ProfileBaseline, Post,
            MetricSnapshot, Alert, ListeningMatch, PollConfig, ChatMessage, LegacyImportMap, User,
        )
    }  # fmt: skip


def test_imports_profiles_merges_duplicates_and_skips_bad_rows(legacy):
    out = run(legacy)
    user = User.objects.get(email="importado@lumi.invalid")
    assert not user.has_usable_password()
    assert sorted(SocialProfile.objects.values_list("id", flat=True)) == [1, 2]
    p1 = SocialProfile.objects.get(pk=1)
    assert p1.user == user and p1.handle.handle_normalized == "atehofficial"
    assert (
        p1.handle.handle_display == "AtehOfficial" and p1.handle.display_name == "Ateh"
    )
    assert (p1.timezone, p1.timezone_source) == ("Africa/Lagos", "user_confirmed")
    assert p1.created_at.isoformat().startswith("2026-01-01T12:00:00")
    # profile 3 merged into 1, 4 (platform) and 5 (handle) skipped and reported
    mapped = dict(
        LegacyImportMap.objects.filter(source_table="profiles", target_table="social_profiles")
        .values_list("source_pk", "target_pk")
    )  # fmt: skip
    assert mapped == {"1": 1, "2": 2, "3": 1}
    assert set(
        LegacyImportMap.objects.filter(source_table="profiles", target_table="(omitida)")
        .values_list("source_pk", flat=True)
    ) == {"4", "5"}  # fmt: skip
    assert (
        "profiles 4: plataforma desconocida" in out
        and "profiles 3: mismo handle" in out
    )


def test_row_counts_per_table_prove_no_data_is_lost(legacy):
    run(legacy)
    assert "Verificación correcta" in run(legacy, "--verify")
    for table, expected in {
        "profiles": 5, "profile_snapshots": 4, "profile_baseline": 2, "posts": 5,
        "metric_snapshots": 5, "user_activity": 4, "listening_matches": 4,
        "poll_config": 3, "chat_messages": 5,
    }.items():  # fmt: skip
        accounted = (
            LegacyImportMap.objects.filter(source_table=table)
            .values("source_pk")
            .distinct()
            .count()
        )
        assert accounted == expected, table


def test_spot_checks_on_values(legacy):
    run(legacy)
    ateh = SocialProfile.objects.get(pk=1).handle_id
    # snapshots: profiles 1 and 3 share a handle and a time, the greater legacy id wins
    snaps = HandleSnapshot.objects.filter(handle_id=ateh).order_by("captured_at")
    assert [(s.followers, s.source) for s in snaps] == [(150, "xpoz"), (None, None)]
    base = ProfileBaseline.objects.get(profile_id=1)
    assert (base.n_posts, base.median_views, base.baseline_reliable) == (
        12,
        500.5,
        True,
    )
    # posts: ids kept, kind None becomes original, conversation None becomes ''
    p10 = Post.objects.get(pk=10)
    assert (p10.kind, p10.conversation_id, p10.author_id) == ("original", "", ateh)
    assert Post.objects.get(pk=11).kind == "reply"
    assert (
        Post.objects.get(pk=13).kind == "original"
    )  # unknown kind falls back, reported
    assert not Post.objects.filter(pk=12).exists()  # same handle and id as 10: merged
    assert not Post.objects.filter(caption="orphan").exists()  # profile 4 was skipped
    # metrics: post 12 merged into 10, and for the same (post, time) the greater legacy id wins
    m1 = MetricSnapshot.objects.get(post_id=10, captured_at__day=3)
    assert (m1.likes, m1.shares, m1.views) == (7, None, 120)
    # a missing metric stays NULL, a negative becomes NULL
    m2 = MetricSnapshot.objects.get(post_id=10, captured_at__day=4)
    assert (m2.comments, m2.shares) == (None, None)
    assert MetricSnapshot.objects.get(post_id=11).likes is None
    # alerts: spike from alerted_at, dismissed keeps no dismissed_at
    a10 = Alert.objects.get(post_id=10, kind="spike")
    assert (a10.status, a10.trigger, a10.created_at.day) == ("active", None, 4)
    a11 = Alert.objects.get(post_id=11)
    assert a11.status == "dismissed" and a11.dismissed_at is None
    # activity: reply with metrics becomes a post and a snapshot
    reply = Post.objects.get(author_id=ateh, platform_post_id="r-1")
    assert reply.kind == "reply"
    snap = reply.metric_snapshots.get()
    assert (snap.likes, snap.comments, snap.views, snap.captured_at.day) == (
        3,
        1,
        40,
        6,
    )
    assert Post.objects.get(author_id=ateh, platform_post_id="rt-1").kind == "retweet"
    assert Post.objects.get(author_id=ateh, platform_post_id="p-1").kind == "original"
    assert not Post.objects.filter(platform_post_id="x-1").exists()
    # listening
    sama = SocialHandle.objects.get(platform="x", handle_normalized="sama")
    assert (sama.handle_display, sama.origin) == ("Sama", "niche")
    n1 = Post.objects.get(author=sama, platform_post_id="n-1")
    assert n1.url.endswith("n-1") and n1.published_at is None
    s = n1.metric_snapshots.get()
    assert (s.likes, s.comments, s.shares, s.views) == (900, 20, 30, 5000)
    assert ListeningMatch.objects.filter(profile_id=1).count() == 2
    assert Alert.objects.get(post=n1, kind="niche_match").status == "dismissed"
    # poll config: one per profile, bad interval clamped
    assert PollConfig.objects.get(profile_id=1).interval_minutes == 15
    assert PollConfig.objects.get(profile_id=2).interval_minutes == 1440
    # chat keeps ids and order, maps role and arrays
    assert list(ChatMessage.objects.order_by("id").values_list("id", "role")) == [
        (1, "user"), (2, "assistant"), (3, "tool"), (4, "user"),
    ]  # fmt: skip
    msg = ChatMessage.objects.get(pk=2)
    assert msg.tools_used == ["get_posts"] and msg.tool_calls[0]["name"] == "get_posts"
    assert ChatMessage.objects.get(pk=4).profile_id == 1  # reassigned to the survivor


def test_second_run_changes_nothing(legacy):
    run(legacy)
    before = counts()
    out = run(legacy)
    assert counts() == before
    assert "importadas 0" in out


def test_sequences_move_past_imported_ids(legacy):
    run(legacy)
    handle_id = SocialProfile.objects.get(pk=1).handle_id
    assert Post.objects.create(author_id=handle_id, platform_post_id="new").pk > 13
    assert ChatMessage.objects.create(profile_id=1, role="user", content="x").pk > 4
    assert SocialProfile.objects.create(
        user=User.objects.get(email="importado@lumi.invalid"),
        handle=SocialHandle.objects.get(handle_normalized="sama"),
    ).pk > 2  # fmt: skip


def test_dry_run_saves_nothing(legacy):
    out = run(legacy, "--dry-run")
    assert "Simulacro" in out and "importadas 2" in out
    assert not User.objects.filter(email="importado@lumi.invalid").exists()
    assert counts() == dict.fromkeys(counts(), 0)


def test_source_file_is_never_modified(legacy):
    before = sha(legacy)
    run(legacy)
    run(legacy, "--verify")
    assert sha(legacy) == before


def test_output_and_stored_columns_hold_no_plain_secret(legacy):
    from django.db import connection

    out = run(legacy)
    assert "pfm-secret" not in out
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT payload FROM legacy_import_map WHERE payload IS NOT NULL"
        )
        assert not any("pfm-secret" in raw for (raw,) in cursor.fetchall())


def test_user_option_names_the_owner(legacy):
    run(legacy, "--user", "Maria@Example.com")
    assert SocialProfile.objects.get(pk=1).user.email == "maria@example.com"


def test_verify_fails_for_a_table_nobody_imports(legacy, tmp_path):
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{legacy}")
    with engine.begin() as c:
        c.execute(text("INSERT INTO style_answers (id, profile_id, question_key, answer, created_at)"
                       " VALUES (1, 1, 'q', 'a', '2026-01-01 00:00:00')"))  # fmt: skip
    engine.dispose()
    run(legacy)
    with pytest.raises(CommandError, match="style_answers.*sin importador"):
        run(legacy, "--verify")


def test_verify_fails_when_nothing_was_imported(legacy):
    with pytest.raises(CommandError, match="profiles"):
        run(legacy, "--verify")


def test_empty_legacy_db_imports_cleanly(tmp_path):
    empty = build_legacy_db(tmp_path / "empty.db", populate=False)
    run(empty)
    assert run(empty, "--verify")
    assert SocialProfile.objects.count() == 0


def test_conflicting_target_rows_abort_without_a_partial_import(legacy):
    from apps.profiles import services

    other = User.objects.create_user("other@example.com")
    hid = services.get_or_create_handle("x", "someone", origin="profile")
    SocialProfile.objects.create(id=2, user=other, handle_id=hid)  # takes legacy id 2
    with pytest.raises(CommandError, match="social_profiles: el id 2 ya existe"):
        run(legacy)
    assert not LegacyImportMap.objects.exists()
    assert not ChatMessage.objects.exists()


def test_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(CommandError, match="No existe el archivo"):
        run(tmp_path / "nope.db")


def test_legacy_tables_list_matches_the_legacy_models():
    from sqlmodel import SQLModel

    import app.models  # noqa: F401

    assert set(LEGACY_TABLES) == set(SQLModel.metadata.tables)
    assert connection.vendor == "postgresql"


def test_import_needs_the_encryption_key(legacy, settings):
    settings.TOKEN_ENCRYPTION_KEY = ""
    with pytest.raises(CommandError, match="TOKEN_ENCRYPTION_KEY"):
        run(legacy)
    assert not LegacyImportMap.objects.exists()


# ------------------------------------------------------------------ zero verifiable loss


def legacy_rows(path):
    """Every legacy row as the importer saw it, after the same JSON round trip."""
    from apps.core.legacy_import import LegacyDb

    db = LegacyDb(str(path))
    try:
        return {
            table: {
                str(row["id"]): json.loads(json.dumps(row, default=str))
                for row in db.rows(table)
            }
            for table in LEGACY_TABLES
        }
    finally:
        db.close()


def test_every_legacy_row_is_imported_or_kept_with_its_payload(legacy):
    run(legacy)
    source = legacy_rows(legacy)
    entries = {}
    for entry in LegacyImportMap.objects.all():
        entries.setdefault((entry.source_table, entry.source_pk), []).append(entry)
    for table, rows in source.items():
        for pk, row in rows.items():
            found = entries.get((table, pk))
            if not found and table in {
                "profiles", "profile_snapshots", "profile_baseline", "posts",
                "metric_snapshots", "user_activity", "listening_matches",
                "poll_config", "chat_messages",
            }:  # fmt: skip
                pytest.fail(f"{table} {pk} has no entry in legacy_import_map")
            for entry in found or []:
                if entry.outcome in ("merged", "skipped"):
                    assert json.loads(entry.payload) == row, (table, pk)
    outcomes = {e.outcome for es in entries.values() for e in es}
    assert outcomes == {"imported", "merged", "skipped"}


def test_the_duplicate_metric_reading_of_post_12_is_not_lost(legacy):
    run(legacy)
    # Post 12 merged into post 10. Reading 1 (post 10) and reading 3 (post 12) share a time.
    # Reading 3 wins the row, reading 1 stays whole in the map.
    winner = MetricSnapshot.objects.get(post_id=10, captured_at__day=3)
    assert winner.likes == 7
    lost = LegacyImportMap.objects.get(source_table="metric_snapshots", source_pk="1")
    assert (lost.outcome, lost.target_pk) == ("merged", winner.pk)
    body = json.loads(lost.payload)
    assert (body["post_id"], body["likes"], body["comments"], body["views"]) == (
        10,
        5,
        1,
        100,
    )
    assert body["age_hours"] == 24.0
    post12 = LegacyImportMap.objects.get(source_table="posts", source_pk="12")
    assert (post12.outcome, post12.target_pk) == ("merged", 10)
    assert json.loads(post12.payload)["caption"] == "hello again"


def test_merged_profile_keeps_its_pfm_id_only_encrypted(legacy):
    from django.db import connection

    run(legacy)
    entry = LegacyImportMap.objects.get(source_table="profiles", source_pk="3")
    assert json.loads(entry.payload)["pfm_account_id"] == "pfm-secret-333"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT payload FROM legacy_import_map WHERE source_pk = '3' AND source_table = 'profiles'"
        )
        raw = cursor.fetchone()[0]
    assert "pfm-secret" not in raw


def test_adjusted_rows_keep_the_original_values(legacy):
    run(legacy)
    negative = LegacyImportMap.objects.get(
        source_table="metric_snapshots", source_pk="4"
    )
    assert (
        negative.outcome == "imported" and json.loads(negative.payload)["likes"] == -3
    )
    odd_kind = LegacyImportMap.objects.get(source_table="posts", source_pk="13")
    assert json.loads(odd_kind.payload)["kind"] == "weird"
    clamped = LegacyImportMap.objects.get(source_table="poll_config", source_pk="3")
    assert json.loads(clamped.payload)["interval_minutes"] == 99999
    reused = LegacyImportMap.objects.get(
        source_table="listening_matches", source_pk="1"
    )
    assert reused.payload is None  # its post was new, nothing was dropped


def test_database_refuses_a_discarded_row_without_payload(legacy):
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        LegacyImportMap.objects.create(
            source_table="posts", source_pk="1", target_table="posts", target_pk=1,
            outcome="merged",
        )  # fmt: skip


def test_remember_refuses_a_merge_without_the_row():
    from apps.core.legacy_import import ImportContext

    ctx = ImportContext(None, None)
    with pytest.raises(ValueError, match="needs the legacy row"):
        ctx.remember("posts", 1, "posts", 1, outcome="merged")


def test_verify_counts_merged_and_skipped_as_accounted_for(legacy):
    run(legacy)
    out = run(legacy, "--verify")
    assert (
        "metric_snapshots: origen 5, registradas 5 (importadas 3, fusionadas 1, omitidas 1)"
        in out
    )
    assert (
        "profiles: origen 5, registradas 5 (importadas 2, fusionadas 1, omitidas 2)"
        in out
    )


def test_verify_flags_a_missing_payload(legacy):
    from django.db import connection

    run(legacy)
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE legacy_import_map DROP CONSTRAINT ck_legacy_import_map_payload"
        )
        cursor.execute(
            "UPDATE legacy_import_map SET payload = NULL WHERE source_table = 'posts' AND outcome = 'merged'"
        )
    with pytest.raises(CommandError, match="posts \\(difiere\\)"):
        run(legacy, "--verify")
