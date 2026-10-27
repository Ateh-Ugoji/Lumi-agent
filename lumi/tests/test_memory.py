import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import memory as memory_service
from app.services.memory import (
    MEMORY_FILE_HEADER,
    append_profile_bullet,
    decay_memories,
    extract_turn_memories,
    get_profile_summary,
    remember,
    upsert_profile_summary,
)

# ── memory.md rolling summary ──────────────────────────────────────────────


def test_get_profile_summary_missing_file(tmp_path: Path):
    assert get_profile_summary(2, path=tmp_path / "memory.md") == ""


def test_upsert_creates_and_replaces_section(tmp_path: Path):
    p = tmp_path / "memory.md"
    upsert_profile_summary(2, "- posts daily", handle="AtehOfficial", path=p)
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# Agent Memory")
    assert "## Profile 2 (@AtehOfficial)" in text
    assert "- posts daily" in text

    # Replace the section with a new rolling summary
    upsert_profile_summary(2, "- posts daily\n- prefers short hooks", path=p)
    text = p.read_text(encoding="utf-8")
    assert text.count("## Profile 2") == 1
    assert "- prefers short hooks" in text

    # Other profiles are untouched when added
    upsert_profile_summary(16, "- different profile", handle="just_ateh", path=p)
    text = p.read_text(encoding="utf-8")
    assert "## Profile 16 (@just_ateh)" in text
    assert text.count("## Profile ") == 2
    assert get_profile_summary(2, path=p) == "- posts daily\n- prefers short hooks"
    assert get_profile_summary(16, path=p) == "- different profile"


def test_upsert_strips_llm_echoed_header(tmp_path: Path):
    p = tmp_path / "memory.md"
    upsert_profile_summary(2, "## Profile 2 (@x)\n- real bullet", path=p)
    assert get_profile_summary(2, path=p) == "- real bullet"


def test_append_profile_bullet_idempotent(tmp_path: Path):
    p = tmp_path / "memory.md"
    assert append_profile_bullet(2, "uses dark mode", path=p) is True
    assert append_profile_bullet(2, "uses dark mode", path=p) is False
    assert append_profile_bullet(2, "", path=p) is False
    assert get_profile_summary(2, path=p) == "- uses dark mode"


# ── Chroma remember / recall / decay ───────────────────────────────────────


def test_remember_noop_when_chroma_down():
    with patch.object(memory_service, "get_collection", return_value=None):
        assert remember(2, "likes short hooks")["stored"] is False


def test_remember_dedupes_exact_match():
    col = MagicMock()
    col.get.return_value = {"ids": ["2:abc"], "documents": ["likes short hooks"]}
    with patch.object(memory_service, "get_collection", return_value=col):
        res = remember(2, "likes short hooks")
    assert res["stored"] is False
    assert res["reason"] == "duplicate"
    col.add.assert_not_called()


def test_remember_adds_new_fact():
    col = MagicMock()
    col.get.return_value = {"ids": [], "documents": []}
    with patch.object(memory_service, "get_collection", return_value=col):
        res = remember(2, "ships on Fridays", kind="preference")
    assert res["stored"] is True
    assert res["id"].startswith("2:")
    kwargs = col.add.call_args.kwargs
    assert kwargs["documents"] == ["ships on Fridays"]
    assert kwargs["metadatas"][0]["kind"] == "preference"
    assert kwargs["metadatas"][0]["access_count"] == 0


def test_decay_removes_only_stale():
    col = MagicMock()
    col.get.return_value = {
        "ids": ["old", "recent", "no-ts"],
        "metadatas": [
            {"created_at": "2020-01-01T00:00:00+00:00", "last_accessed": "2020-01-01T00:00:00+00:00"},
            {"created_at": "2099-01-01T00:00:00+00:00", "last_accessed": "2099-01-01T00:00:00+00:00"},
            {"kind": "fact"},
        ],
    }
    with patch.object(memory_service, "get_collection", return_value=col):
        removed = decay_memories(90)
    assert removed == 1
    col.delete.assert_called_once_with(ids=["old"])


# ── end-of-turn extraction ─────────────────────────────────────────────────


async def test_extract_skips_without_llm_keys(tmp_path: Path):
    with patch.object(memory_service, "get_settings") as s:
        s.return_value.groq_api_key = ""
        s.return_value.openrouter_api_key = ""
        out = await extract_turn_memories(2, "hi", "hello", path=tmp_path / "memory.md")
    assert out["skipped"] == "no_llm_keys"


async def test_extract_success_updates_summary_and_stores(tmp_path: Path):
    p = tmp_path / "memory.md"
    payload = {"memories": ["ships daily"], "summary": "- ships daily\n- builder in Lagos"}
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]

    with (
        patch.object(memory_service, "get_settings") as s,
        patch.object(memory_service, "chat_completion_with_fallback", new=AsyncMock(return_value=completion)),
        patch.object(memory_service, "get_collection", return_value=MagicMock(get=MagicMock(return_value={"ids": []}))),
    ):
        s.return_value.groq_api_key = "k"
        s.return_value.openrouter_api_key = ""
        out = await extract_turn_memories(
            2, "I ship daily", "Nice, keep it up", handle="AtehOfficial", path=p
        )

    assert out["stored"] == 1
    assert out["summary_updated"] is True
    summary = get_profile_summary(2, path=p)
    assert "- ships daily" in summary
    assert "- builder in Lagos" in summary


async def test_extract_failure_writes_nothing(tmp_path: Path):
    p = tmp_path / "memory.md"
    p.write_text(MEMORY_FILE_HEADER, encoding="utf-8")
    with (
        patch.object(memory_service, "get_settings") as s,
        patch.object(
            memory_service,
            "chat_completion_with_fallback",
            new=AsyncMock(side_effect=RuntimeError("all LLM providers failed")),
        ),
    ):
        s.return_value.groq_api_key = "k"
        s.return_value.openrouter_api_key = ""
        out = await extract_turn_memories(2, "hi", "there", path=p)

    assert "error" in out
    assert get_profile_summary(2, path=p) == ""
