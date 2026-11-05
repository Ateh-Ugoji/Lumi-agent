from lumi_ai.ports import MediaRef
from lumi_ai.video.urls import looks_like_video, video_urls


def _ref(url, kind=None):
    return MediaRef(kind=kind, url=url)


def test_a_video_kind_always_goes_through() -> None:
    chosen, skipped = video_urls([_ref("https://cdn.example.com/a?sig=1", "video")])
    assert chosen == ["https://cdn.example.com/a?sig=1"] and skipped == []


def test_unknown_kind_goes_through_only_when_the_url_says_video() -> None:
    refs = [
        _ref("https://video.twimg.com/ext_tw_video/1/vid/a.mp4?tag=12"),
        _ref("https://pbs.twimg.com/media/abc.jpg"),
        _ref("https://cdn.example.com/blob/123"),
    ]
    chosen, skipped = video_urls(refs)
    assert chosen == ["https://video.twimg.com/ext_tw_video/1/vid/a.mp4?tag=12"]
    assert skipped == [
        "https://pbs.twimg.com/media/abc.jpg",
        "https://cdn.example.com/blob/123",
    ]


def test_images_and_gifs_never_go_through_even_with_a_video_looking_url() -> None:
    chosen, _ = video_urls(
        [_ref("https://x.com/a.mp4", "gif"), _ref("https://x.com/b.mp4", "image")]
    )
    assert chosen == []


def test_pasted_urls_count_when_they_are_http_and_dedupe() -> None:
    chosen, skipped = video_urls(
        [_ref("https://a.com/v.mp4", "video")],
        pasted=[
            "https://a.com/v.mp4",
            "https://t.co/xyz",
            "javascript:alert(1)",
            "ftp://a/b.mp4",
        ],
    )
    assert chosen == ["https://a.com/v.mp4", "https://t.co/xyz"]
    assert skipped == ["javascript:alert(1)", "ftp://a/b.mp4"]


def test_looks_like_video_rejects_non_http() -> None:
    assert not looks_like_video("file:///tmp/a.mp4")
    assert looks_like_video("https://youtu.be/abc")
