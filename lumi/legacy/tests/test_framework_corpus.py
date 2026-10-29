from unittest.mock import MagicMock, patch

from app.models.frameworks import PeerFramework
from app.services.framework_corpus import (
    framework_document,
    query_frameworks,
    upsert_framework,
    upsert_peer_posts,
)

PAYLOAD = {
    "niche_title": "Nigerian Tech Founders",
    "top_peer_handles": ["sama", "levelsio"],
    "content_pillars": [
        {
            "pillar_name": "Build in public",
            "percentage_of_posts": 40,
            "description": "Shipping updates",
            "why_it_works": "creates accountability",
        }
    ],
    "winning_frameworks": [
        {
            "framework_name": "The Build Log",
            "structure": ["Context", "Ship", "Ask"],
            "hook_formula": "I shipped X today",
            "engagement_driver": "curiosity + open loop",
        }
    ],
    "pacing_and_format_rules": {"cadence": "1-2 posts daily"},
    "actionable_post_prompts": ["Post a ship log with one screenshot"],
}


def test_framework_document_renders_all_sections():
    doc = framework_document(PAYLOAD)
    assert "Niche: Nigerian Tech Founders" in doc
    assert "@sama" in doc
    assert "Content pillar: Build in public" in doc
    assert "Winning framework: The Build Log" in doc
    assert "Context > Ship > Ask" in doc
    assert "Pacing/format rule — cadence: 1-2 posts daily" in doc
    assert "Actionable post prompt: Post a ship log" in doc


def test_framework_document_empty_payload():
    assert framework_document({}) == ""


def test_upsert_framework_indexes_row():
    col = MagicMock()
    row = PeerFramework(id=5, profile_id=2, query="founders", niche_title="NTF", payload=PAYLOAD)
    with patch("app.services.framework_corpus.get_collection", return_value=col):
        assert upsert_framework(2, row) is True
    col.upsert.assert_called_once()
    kwargs = col.upsert.call_args.kwargs
    assert kwargs["ids"] == ["2:5"]
    assert "Winning framework" in kwargs["documents"][0]
    assert kwargs["metadatas"][0]["profile_id"] == 2
    assert kwargs["metadatas"][0]["framework_id"] == 5


def test_upsert_framework_noop_without_row_id():
    col = MagicMock()
    row = PeerFramework(id=None, profile_id=2, payload=PAYLOAD)
    with patch("app.services.framework_corpus.get_collection", return_value=col):
        assert upsert_framework(2, row) is False
    col.upsert.assert_not_called()


def test_upsert_peer_posts_builds_ids_and_meta():
    col = MagicMock()
    posts = [
        {"id": "111", "text": "shipped daily for 30 days", "authorUsername": "@levelsio", "impressionCount": 5000},
        {"id": "", "text": "no id post", "authorUsername": "sama", "impressionCount": 2000},
        {"id": "333", "text": "   ", "authorUsername": "x", "impressionCount": 100},
    ]
    with patch("app.services.framework_corpus.get_collection", return_value=col):
        n = upsert_peer_posts(2, "building in public", posts)
    assert n == 2  # empty text skipped
    kwargs = col.upsert.call_args.kwargs
    assert kwargs["ids"][0] == "2:111"
    assert kwargs["ids"][1].startswith("2:")  # hashed fallback id
    assert kwargs["metadatas"][0]["author"] == "levelsio"
    assert kwargs["metadatas"][0]["impressions"] == 5000
    assert kwargs["metadatas"][0]["query"] == "building in public"


def test_query_frameworks_returns_empty_when_chroma_down():
    with patch("app.services.framework_corpus.get_collection", return_value=None):
        assert query_frameworks(1, "hooks") == []


def test_query_frameworks_returns_empty_when_profile_has_nothing():
    col = MagicMock()
    col.get.return_value = {"ids": []}  # nothing indexed for this profile
    with patch("app.services.framework_corpus.get_collection", return_value=col):
        assert query_frameworks(2, "hooks") == []
    col.query.assert_not_called()


def test_query_frameworks_maps_hits():
    col = MagicMock()
    col.get.return_value = {"ids": ["x"]}
    col.query.return_value = {
        "ids": [["2:5"]],
        "documents": [["Winning framework: The Build Log"]],
        "metadatas": [[{"profile_id": 2, "framework_id": 5}]],
        "distances": [[0.31]],
    }
    with patch("app.services.framework_corpus.get_collection", return_value=col):
        hits = query_frameworks(2, "launch hooks")
    assert len(hits) == 1
    assert hits[0]["id"] == "2:5"
    assert hits[0]["distance"] == 0.31
    assert hits[0]["metadata"]["framework_id"] == 5
