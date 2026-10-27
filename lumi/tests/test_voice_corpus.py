from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.voice_corpus import retrieve_extraction_sample, upsert_posts


def _fake_col(get_result):
    col = MagicMock()
    col.get.return_value = get_result
    return col


def test_upsert_posts_skips_empty_and_none_ids():
    col = MagicMock()
    posts = [
        SimpleNamespace(id=1, caption="Hello world", published_at=datetime.now(UTC)),
        SimpleNamespace(id=None, caption="No id", published_at=datetime.now(UTC)),
        SimpleNamespace(id=3, caption="   ", published_at=datetime.now(UTC)),
    ]
    with patch("app.services.voice_corpus.get_collection", return_value=col):
        n = upsert_posts(7, posts)
    assert n == 1
    col.upsert.assert_called_once()
    kwargs = col.upsert.call_args.kwargs
    assert kwargs["ids"] == ["7:1"]
    assert kwargs["documents"] == ["Hello world"]
    assert kwargs["metadatas"][0]["profile_id"] == 7
    assert kwargs["metadatas"][0]["post_id"] == 1


def test_upsert_posts_noop_when_chroma_down():
    with patch("app.services.voice_corpus.get_collection", return_value=None):
        assert upsert_posts(1, [SimpleNamespace(id=1, caption="x", published_at=None)]) == 0


def test_retrieve_sample_returns_none_when_empty():
    col = _fake_col({"documents": [], "metadatas": []})
    with patch("app.services.voice_corpus.get_collection", return_value=col):
        assert retrieve_extraction_sample(1) is None


def test_retrieve_sample_returns_all_when_under_limit():
    docs = ["a", "b", "c"]
    metas = [{"post_id": i + 1, "published_at": ""} for i in range(3)]
    col = _fake_col({"documents": docs, "metadatas": metas})
    with patch("app.services.voice_corpus.get_collection", return_value=col):
        sample = retrieve_extraction_sample(1, limit=10)
    assert sample is not None
    assert [s["caption"] for s in sample] == ["a", "b", "c"]
    assert [s["post_id"] for s in sample] == [1, 2, 3]


def test_retrieve_sample_spreads_across_history():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    docs = [f"post-{i}" for i in range(20)]
    metas = [{"post_id": i + 1, "published_at": (base + timedelta(days=i)).isoformat()} for i in range(20)]
    col = _fake_col({"documents": docs, "metadatas": metas})
    with patch("app.services.voice_corpus.get_collection", return_value=col):
        sample = retrieve_extraction_sample(1, limit=5)
    assert sample is not None
    captions = [s["caption"] for s in sample]
    # Should pick a spread (every ~4th), not just the first 5
    assert len(captions) == 5
    assert captions == ["post-0", "post-4", "post-8", "post-12", "post-16"]
    assert captions != docs[:5]
