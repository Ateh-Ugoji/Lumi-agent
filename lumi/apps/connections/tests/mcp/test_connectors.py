from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from apps.connections.mcp.connectors import (
    CONNECTORS,
    MCPConnector,
    connector_enabled,
    get_connector,
    google_consent_url,
    google_scope_union,
    is_confirmation,
    mcp_enabled,
    requires_confirmation,
    tool_spec_name,
)

GDRIVE = get_connector("gdrive")
GDOCS = get_connector("gdocs")


@pytest.mark.parametrize(
    "tool",
    [
        "create_file",
        "copy_file",  # no write verb in the name, and still a write
        "update_doc",
        "delete_file",
        "share_file",
        "some_tool_added_next_year",
        "Search_Files",  # a lookalike is not the allow-listed name
        "search_files ",
        "",
    ],
)
def test_anything_not_listed_as_read_only_is_gated(tool):
    assert requires_confirmation(GDRIVE, tool)


@pytest.mark.parametrize(
    "tool",
    [
        "search_files",
        "read_file_content",
        "download_file_content",
        "get_file_metadata",
        "get_file_permissions",
        "list_recent_files",
    ],
)
def test_only_the_listed_drive_reads_run_freely(tool):
    assert not requires_confirmation(GDRIVE, tool)


def test_docs_reads_are_free_and_its_update_is_gated():
    assert not requires_confirmation(GDOCS, "read_doc")
    assert requires_confirmation(GDOCS, "update_doc")
    # A read-only tool of one connector is not read-only on the other.
    assert requires_confirmation(GDOCS, "search_files")


def test_a_connector_with_no_read_only_list_gates_every_tool():
    bare = MCPConnector(name="x", url="https://x.invalid/mcp")
    assert requires_confirmation(bare, "search_files")


def test_a_connector_that_turns_the_gate_off_gates_nothing():
    open_ = MCPConnector(name="x", url="https://x.invalid/mcp", confirm_writes=False)
    assert not requires_confirmation(open_, "delete_everything")


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
