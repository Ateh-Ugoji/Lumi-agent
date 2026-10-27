from datetime import UTC, datetime

from app.models.post import Post
from app.services.pfm import classify_post_kind, is_authentic_original
from app.services.voice import VoiceProfilePayload


def test_classify_post_kind():
    assert classify_post_kind("@tsola_ps 😂😂") == "reply"
    assert classify_post_kind("RT @someone: great thread") == "retweet"
    assert classify_post_kind("rt: old-style marker") == "retweet"
    assert classify_post_kind("Don't run out of money.") == "original"
    assert classify_post_kind("“my take” — quote keeps own words") == "original"


def test_reply_style_defaults_empty():
    payload = VoiceProfilePayload(tone="t", emoji_use="e", hook_style="h", vocabulary="v", structure="s", things_they_never_do="n")
    assert payload.reply_style == ""


def test_rt_variants_are_rejected():
    assert not is_authentic_original("RT @someone: great thread on agents")
    assert not is_authentic_original("rt @someone: lower-case prefix")
    assert not is_authentic_original("RT: just an old-style retweet marker")
    assert not is_authentic_original("RT someone forgot the at-sign")


def test_replies_and_mention_openers_are_rejected():
    assert not is_authentic_original("@tsola_ps 😂😂")
    assert not is_authentic_original("@lou3ee Just sent a DM 💙")
    assert not is_authentic_original("  @leading_space still a reply")
    assert not is_authentic_original("@")


def test_original_posts_and_quotes_are_kept():
    assert is_authentic_original("Don't run out of money. That's the whole job.")
    assert is_authentic_original("Great to catch up, @Shalom_heyeliy! Dream bigger.")
    assert is_authentic_original("Everyone: 'Got accepted in 2mins'. Me: https://t.co/abc")
    assert is_authentic_original("“Shirt by Chizi” — my take on event fashion https://t.co/xyz")


def test_empty_and_whitespace_are_rejected():
    assert not is_authentic_original("")
    assert not is_authentic_original(None)
    assert not is_authentic_original("   ")


def test_upsert_posts_skips_polluted_captions(monkeypatch):
    import app.services.voice_corpus as vc

    captured: dict = {}

    class FakeCol:
        def upsert(self, ids=None, documents=None, metadatas=None):
            captured["ids"] = ids
            captured["documents"] = documents

    monkeypatch.setattr(vc, "get_collection", lambda name: FakeCol())

    good = Post(profile_id=1, platform_post_id="a1", caption="my own post", published_at=datetime.now(UTC))
    good.id = 1
    bad = Post(profile_id=1, platform_post_id="a2", caption="RT @x: not mine", published_at=datetime.now(UTC))
    bad.id = 2
    reply = Post(profile_id=1, platform_post_id="a3", caption="@friend hey", published_at=datetime.now(UTC))
    reply.id = 3

    n = vc.upsert_posts(1, [good, bad, reply])
    assert n == 1
    assert captured["documents"] == ["my own post"]
