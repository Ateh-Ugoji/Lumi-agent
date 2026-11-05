"""T8: the CONNECT importers (mcp_auth_accounts and the pfm accounts of profiles.pfm_account_id).

The legacy file is synthetic (built with the legacy models by ARCHITECT's helper). The values
that look like secrets must not reach the output or the warnings.
"""

from __future__ import annotations

import sqlite3
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection

from apps.accounts.models import User
from apps.connections.models import AccountStatus, ConnectedAccount, McpAuthAccount
from apps.core.tests.legacy_db import build_legacy_db

pytestmark = pytest.mark.django_db

ACCESS = "ya29.legacy-access-SECRET"
REFRESH = "1//legacy-refresh-SECRET"


@pytest.fixture
def legacy(tmp_path):
    path = build_legacy_db(tmp_path / "lumi.db")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO mcp_auth_accounts (id, account, access_token, refresh_token,"
            " token_type, scopes, expires_at, updated_at) VALUES"
            " (1, 'google', ?, ?, 'Bearer', 'drive.readonly documents', '2026-01-02 03:04:05',"
            " '2026-01-01 00:00:00')",
            (ACCESS, REFRESH),
        )
    return path


def run(path, *args):
    out = StringIO()
    call_command("import_legacy", "--sqlite", str(path), *args, stdout=out)
    return out.getvalue()


def test_imports_the_google_grant_encrypted_for_the_imported_user(legacy):
    out = run(legacy)
    user = User.objects.get(email="importado@lumi.invalid")
    row = McpAuthAccount.objects.get(user=user, account="google")
    assert (row.access_token, row.refresh_token) == (ACCESS, REFRESH)
    assert row.scopes == ["drive.readonly", "documents"]
    assert row.expires_at.isoformat().startswith("2026-01-02T03:04:05")
    with connection.cursor() as cursor:
        cursor.execute("SELECT access_token, refresh_token FROM mcp_auth_accounts")
        stored = cursor.fetchone()
    assert ACCESS not in stored[0] and REFRESH not in stored[1]
    assert "SECRET" not in out


def test_creates_pfm_accounts_for_real_ids_and_none_for_demo_ids(legacy):
    out = run(legacy)
    accounts = ConnectedAccount.objects.filter(provider="pfm")
    assert [a.external_account_id for a in accounts] == ["pfm-secret-111"]
    account = accounts.get()
    assert account.social_profile_id == 1
    assert account.user.email == "importado@lumi.invalid"
    assert account.platform == "x" and account.status == AccountStatus.ACTIVE
    assert account.handle
    # profile 2 holds demo-1: no account. No id reaches the report.
    assert not ConnectedAccount.objects.filter(social_profile_id=2).exists()
    assert "pfm-secret" not in out and "demo-1" not in out


def test_a_merged_profile_does_not_get_a_second_pfm_account(legacy):
    out = run(legacy)
    # Legacy profile 3 merged into 1 and carried another pfm id. One account per profile.
    assert ConnectedAccount.objects.filter(provider="pfm").count() == 1
    assert "profiles 3" in out and "ya tiene una cuenta pfm" in out
    assert "pfm-secret-333" not in out


def test_unmapped_profiles_create_no_account(legacy):
    out = run(legacy)
    # Profiles 4 (unknown platform) and 5 (invalid handle) were dropped by the profiles importer.
    assert not ConnectedAccount.objects.filter(
        external_account_id__in=["p4", "p5"]
    ).exists()
    assert "profiles 4" in out and "profiles 5" in out


def test_second_run_changes_nothing(legacy):
    run(legacy)
    before = (
        list(ConnectedAccount.objects.values_list("pk", "external_account_id")),
        list(McpAuthAccount.objects.values_list("pk", "updated_at")),
    )
    run(legacy)
    after = (
        list(ConnectedAccount.objects.values_list("pk", "external_account_id")),
        list(McpAuthAccount.objects.values_list("pk", "updated_at")),
    )
    assert before == after


def test_dry_run_rolls_back(legacy):
    out = run(legacy, "--dry-run")
    assert not ConnectedAccount.objects.exists() and not McpAuthAccount.objects.exists()
    assert "mcp_auth_accounts" in out


def test_verify_now_covers_the_mcp_table(legacy):
    run(legacy)
    out = run(legacy, "--verify")
    line = next(x for x in out.splitlines() if "mcp_auth_accounts" in x)
    assert "ok" in line and "difiere" not in line


def test_a_token_less_row_is_skipped_without_leaking(tmp_path):
    path = build_legacy_db(tmp_path / "lumi.db")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO mcp_auth_accounts (id, account, access_token, token_type, updated_at)"
            " VALUES (1, 'google', '', 'Bearer', '2026-01-01 00:00:00')"
        )
    out = run(path)
    assert not McpAuthAccount.objects.exists()
    assert "mcp_auth_accounts 1" in out and "sin access token" in out
