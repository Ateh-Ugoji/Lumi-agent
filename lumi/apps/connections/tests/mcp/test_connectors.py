from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from apps.connections.mcp.connectors import (
    CONNECTORS,
    connector_enabled,
    get_connector,
    google_consent_url,
    google_scope_union,
    is_confirmation,
    mcp_enabled,
    requires_confirmation,
    tool_spec_name,
)


@pytest.mark.parametrize(
    "tool",
    [
        "create_file",
        "createFile",
        "docs.update",
        "delete-document",
        "move_file",
        "share_file",
        "batchUpdate",  # camelCase 'batch' + 'Update'
        "insert_text",
        "trash_file",
    ],
)
def test_write_verbs_are_gated(tool):
    assert requires_confirmation(tool)


@pytest.mark.parametrize(
    "tool",
    [
        "search_files",
        "read_document",
        "list_files",
        "get_file_metadata",
        "get_file_created_time",  # 'created' is not 'create'
        "download_file_content",
        "",
    ],
)
def test_read_tools_are_not_gated(tool):
    assert not requires_confirmation(tool)


@pytest.mark.parametrize(
    "message",
    [
        "yes",
        "Yes, go ahead",
        "sure!",
        "ok",
        "do it",
        "sí",
        "si, dale",
        "Sí.",
        "dale",
        "confirmo",
        "Adelante por favor",
        "  proceed",
    ],
)
def test_clear_yes_confirms(message):
    assert is_confirmation(message)


@pytest.mark.parametrize(
    "message",
    [
        "no",
        "yes, but change the title first",
        "yes but not now",
        "sí, pero mañana",
        "si quieres crea otro mejor",  # Spanish 'if', not 'yes'
        "wait",
        "what will it do?",
        "",
        "make it shorter",
        "okay so what files do I have",  # a new request that starts with 'okay'
        "yes create it and also share it with everyone on my team",
        "ok?",
    ],
)
def test_anything_else_does_not_confirm(message):
    assert not is_confirmation(message)


def test_spec_names_are_sanitized_and_prefixed():
    drive = get_connector("gdrive")
    assert drive is not None
    assert tool_spec_name(drive, "files.search v2") == "mcp__gdrive__files_search_v2"


def test_scope_union_has_no_duplicates_and_covers_every_connector():
    scopes = google_scope_union()
    assert len(scopes) == len(set(scopes))
    for connector in CONNECTORS:
        assert set(connector.scopes) <= set(scopes)


def test_consent_url_asks_for_offline_access_and_pkce():
    url = google_consent_url(
        state="st", redirect_uri="http://x/cb", client_id="cid", code_challenge="chal"
    )
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert urlsplit(url).netloc == "accounts.google.com"
    assert q["access_type"] == "offline" and q["prompt"] == "consent"
    assert q["code_challenge"] == "chal" and q["code_challenge_method"] == "S256"
    assert q["state"] == "st" and q["client_id"] == "cid"
    assert set(q["scope"].split()) == set(google_scope_union())


def test_switches_default_on_and_turn_off_per_connector():
    drive = get_connector("gdrive")
    assert drive is not None
    assert mcp_enabled({}) and connector_enabled(drive, {})
    assert not mcp_enabled({"MCP_ENABLED": "false"})
    assert not connector_enabled(drive, {"MCP_GDRIVE_ENABLED": "0"})
    docs = get_connector("gdocs")
    assert docs is not None and connector_enabled(docs, {"MCP_GDRIVE_ENABLED": "0"})
