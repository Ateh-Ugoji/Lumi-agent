"""Legacy handle picks (``--handle-mappings``) land in ``user_saved_handles`` of ``--user``.

The legacy SQLite has no table of saved handles (they lived in Chroma ``handle_mappings``), so
the picks come from a JSON export. ``legacy_handle_mappings.json`` is frozen next to the other
fixtures: 3 usable picks (one repeated), 2 pulls that are not picks and 2 unusable picks.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User
from apps.connections.models import UserSavedHandle
from apps.profiles.models import HandleSnapshot, SocialHandle

from .legacy_db import build_legacy_db

pytestmark = pytest.mark.django_db

MAPPINGS = Path(__file__).parent / "legacy_handle_mappings.json"
OWNER = "maria@example.com"


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


def import_picks(legacy, *extra):
    return run(legacy, "--user", OWNER, "--handle-mappings", str(MAPPINGS), *extra)


def picks_of(email):
    return {
        (p, h): when
        for p, h, when in UserSavedHandle.objects.filter(user__email=email).values_list(
            "handle__platform", "handle__handle_normalized", "created_at"
        )
    }


def test_every_legacy_pick_belongs_to_the_user_option(legacy):
    out = import_picks(legacy)
    got = picks_of(OWNER)
    assert set(got) == {
        ("x", "atehofficial"),
        ("x", "naval"),
        ("instagram", "mrbeast"),
    }
    assert (
        "user_saved_handles: leídas 6, importadas 3, ya importadas 0, fusionadas 1, omitidas 2"
        in out
    )
    assert UserSavedHandle.objects.count() == 3
    assert not User.objects.filter(email="importado@lumi.invalid").exists()


def test_a_pull_is_not_a_pick_and_an_unusable_entry_is_reported(legacy):
    out = import_picks(legacy)
    assert not SocialHandle.objects.filter(
        handle_normalized__in=["paulg", "dhh"]
    ).exists()
    assert not SocialHandle.objects.filter(
        handle_normalized="tom", platform="myspace"
    ).exists()
    assert "aviso: handle_mappings myspace:'tom'" in out
    assert "no se guarda" in out


def test_the_original_save_date_is_kept_and_the_earliest_save_wins(legacy):
    import_picks(legacy)
    got = picks_of(OWNER)
    assert got[("x", "naval")] == datetime.fromtimestamp(1768400000, UTC)
    assert got[("x", "atehofficial")] == datetime.fromtimestamp(1768478400, UTC)
    assert got[("instagram", "mrbeast")] == datetime.fromtimestamp(1768651200, UTC)


def test_a_newer_row_of_the_same_pick_gets_the_original_date(legacy):
    import_picks(legacy, "--dry-run")
    run(legacy, "--user", OWNER)
    user = User.objects.get(email=OWNER)
    handle = SocialHandle.objects.get(platform="x", handle_normalized="atehofficial")
    row = UserSavedHandle.objects.create(
        user=user, handle=handle
    )  # picked again, today
    assert row.created_at.year >= 2026
    import_picks(legacy)
    row.refresh_from_db()
    assert row.created_at == datetime.fromtimestamp(1768478400, UTC)
    assert UserSavedHandle.objects.filter(user=user, handle=handle).count() == 1


def test_the_legacy_card_fills_an_empty_handle_and_never_overwrites(legacy):
    import_picks(legacy)
    naval = SocialHandle.objects.get(platform="x", handle_normalized="naval")
    assert naval.display_name == "Naval"
    assert naval.avatar_url == "https://pbs.example/naval.jpg"
    assert naval.origin == "selected"
    # Repeated entry: the earliest save gives the date and the reading, the later one the name.
    assert naval.follower_count == 2300000
    ateh = SocialHandle.objects.get(platform="x", handle_normalized="atehofficial")
    assert ateh.origin == "profile"  # an origin is never lowered


def test_a_second_run_changes_nothing(legacy):
    import_picks(legacy)
    before = (
        sorted(
            UserSavedHandle.objects.values_list("user_id", "handle_id", "created_at")
        ),
        SocialHandle.objects.count(),
        HandleSnapshot.objects.count(),
    )
    out = import_picks(legacy)
    after = (
        sorted(
            UserSavedHandle.objects.values_list("user_id", "handle_id", "created_at")
        ),
        SocialHandle.objects.count(),
        HandleSnapshot.objects.count(),
    )
    assert after == before
    assert "importadas 0, ya importadas 3" in out


def test_verify_passes_after_the_import(legacy):
    import_picks(legacy)
    out = run(legacy, "--verify", "--user", OWNER, "--handle-mappings", str(MAPPINGS))
    assert "user_saved_handles (handle_mappings): origen 6, registradas 6" in out
    assert "los handles elegidos" in out


def test_verify_fails_when_a_saved_handle_is_missing(legacy):
    import_picks(legacy)
    UserSavedHandle.objects.filter(
        user__email=OWNER, handle__handle_normalized="naval"
    ).delete()
    with pytest.raises(CommandError, match=r"user_saved_handles.*difiere"):
        run(legacy, "--verify", "--user", OWNER, "--handle-mappings", str(MAPPINGS))
    import_picks(legacy)  # the re-run restores it
    run(legacy, "--verify", "--user", OWNER, "--handle-mappings", str(MAPPINGS))


def test_verify_fails_for_a_user_that_owns_none_of_them(legacy):
    import_picks(legacy)
    with pytest.raises(CommandError, match="user_saved_handles"):
        run(
            legacy,
            "--verify",
            "--user",
            "otra@example.com",
            "--handle-mappings",
            str(MAPPINGS),
        )


def test_without_the_file_nothing_is_written_and_verify_has_nothing_to_add(legacy):
    out = run(legacy, "--user", OWNER)
    assert "user_saved_handles" not in out
    assert UserSavedHandle.objects.count() == 0
    assert "user_saved_handles" not in run(legacy, "--verify")


def test_a_legacy_file_with_no_tables_still_takes_the_picks(tmp_path):
    empty = build_legacy_db(tmp_path / "empty.db", populate=False)
    import_picks(empty)
    assert len(picks_of(OWNER)) == 3
    run(empty, "--verify", "--user", OWNER, "--handle-mappings", str(MAPPINGS))


def test_dry_run_saves_no_pick(legacy):
    import_picks(legacy, "--dry-run")
    assert UserSavedHandle.objects.count() == 0
    assert not SocialHandle.objects.filter(handle_normalized="naval").exists()


def test_a_bare_list_of_metadata_is_accepted(legacy, tmp_path):
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps(json.loads(MAPPINGS.read_text())["metadatas"]))
    run(legacy, "--user", OWNER, "--handle-mappings", str(bare))
    assert len(picks_of(OWNER)) == 3


@pytest.mark.parametrize(
    "content",
    ["not json", '"a string"', '{"ids": []}'],
)
def test_a_file_that_is_not_an_export_is_a_clear_error(legacy, tmp_path, content):
    bad = tmp_path / "bad.json"
    bad.write_text(content)
    with pytest.raises(CommandError, match="handle_mappings|JSON"):
        run(legacy, "--user", OWNER, "--handle-mappings", str(bad))
    assert UserSavedHandle.objects.count() == 0


def test_a_missing_file_is_a_clear_error(legacy, tmp_path):
    with pytest.raises(CommandError):
        run(legacy, "--user", OWNER, "--handle-mappings", str(tmp_path / "nope.json"))
