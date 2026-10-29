"""``apps.profiles.services`` against real Postgres: idempotency, NULL preservation, atomicity."""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from asgiref.sync import sync_to_async
from django.db import IntegrityError, connection, connections, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.profiles import hooks, services
from apps.profiles.models import (
    Alert,
    HandleSnapshot,
    ListeningKeyword,
    MetricSnapshot,
    PollConfig,
    Post,
    PostMedia,
    SocialHandle,
    SocialProfile,
)
from lumi_ai.ports import (
    BaselineOut,
    ListeningConfig,
    MediaRef,
    PeerPostIn,
    PostIn,
    PostMetrics,
)

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def user():
    return User.objects.create_user("owner@example.com")


@pytest.fixture
def handle_id():
    return services.get_or_create_handle(
        "x", "@Ateh", origin="profile", display_name="Ateh"
    )


@pytest.fixture
def profile_id(user, handle_id):
    return SocialProfile.objects.create(user=user, handle_id=handle_id).pk


def post_in(external_id="1", **kw):
    base = {
        "platform": "x",
        "external_id": external_id,
        "text": f"post {external_id}",
        "published_at": T0,
        "kind": "original",
    }
    return PostIn(**{**base, **kw})


# ------------------------------------------------------------------ handles


def test_handle_is_normalized_and_reused(handle_id):
    assert services.get_or_create_handle("x", "ATEH") == handle_id
    assert SocialHandle.objects.get(pk=handle_id).handle_normalized == "ateh"


@pytest.mark.parametrize(
    ("platform", "handle"),
    [("x", ""), ("x", "has space"), ("x", "a" * 16), ("nope", "ateh"), ("x", "@@")],
)
def test_invalid_handles_are_refused(platform, handle):
    with pytest.raises(services.InvalidHandle):
        services.get_or_create_handle(platform, handle)


def test_linkedin_handle_may_exceed_the_x_limit():
    assert services.get_or_create_handle("linkedin", "a" * 30)


def test_origin_never_goes_down_and_goes_up():
    hid = services.get_or_create_handle("x", "peer", origin="selected")
    services.get_or_create_handle("x", "peer", origin="niche")
    assert SocialHandle.objects.get(pk=hid).origin == "selected"
    services.get_or_create_handle("x", "peer", origin="profile")
    assert SocialHandle.objects.get(pk=hid).origin == "profile"


def test_existing_fields_are_filled_but_not_overwritten():
    hid = services.get_or_create_handle("x", "peer", display_name="Peer One")
    services.get_or_create_handle(
        "x", "peer", display_name="Other", avatar_url="http://a/x.png"
    )
    row = SocialHandle.objects.get(pk=hid)
    assert (row.display_name, row.avatar_url) == ("Peer One", "http://a/x.png")


def test_follower_count_writes_snapshot_and_denormalized_copy():
    hid = services.get_or_create_handle(
        "x", "peer", follower_count=10, following_count=3, source="xpoz"
    )
    row = SocialHandle.objects.get(pk=hid)
    assert row.follower_count == 10
    assert HandleSnapshot.objects.get(handle_id=hid).following == 3
    older = timezone.now() - timedelta(days=2)
    services.record_handle_snapshot(hid, followers=99, captured_at=older)
    assert (
        SocialHandle.objects.get(pk=hid).follower_count == 10
    )  # an old reading is history only


# ------------------------------------------------------------------ profiles


def test_get_profile_filters_by_user(user, profile_id):
    other = User.objects.create_user("other@example.com")
    info = services.get_profile(profile_id, user.pk)
    assert (info.name, info.handle, info.primary_platform) == ("Ateh", "ateh", "x")
    assert services.get_profile(profile_id, other.pk) is None
    assert services.get_profile(profile_id) is not None
    assert [p.id for p in services.list_profiles(user.pk)] == [profile_id]
    assert services.list_profiles(other.pk) == []


def test_name_falls_back_to_the_handle(user):
    hid = services.get_or_create_handle("x", "Bare")
    pid = SocialProfile.objects.create(user=user, handle_id=hid).pk
    assert services.get_profile(pid).name == "Bare"


def test_connected_platforms_come_from_active_accounts(user, profile_id):
    from apps.connections.models import ConnectedAccount

    ConnectedAccount.objects.create(
        user=user,
        social_profile_id=profile_id,
        provider="pfm",
        external_account_id="a1",
    )
    ConnectedAccount.objects.create(
        user=user,
        social_profile_id=profile_id,
        provider="linkedin",
        external_account_id="a3",
        status="revoked",
    )
    assert services.get_profile(profile_id).connected_platforms == ("x",)


def test_summaries_use_the_readers_and_listening(user, profile_id, monkeypatch):
    monkeypatch.setattr(hooks, "voice_profile_reader", lambda ids: set(ids))
    services.set_listening(ListeningConfig(profile_id, ("ai",), True, 10))
    [summary] = services.list_profile_summaries(user.pk)
    assert summary["has_voice_profile"] is True
    assert summary["listening_active"] is True
    assert summary["platform"] == "x"
    assert services.select_info(profile_id)["post_count"] == 0


def test_summary_query_count_does_not_grow_with_profiles(user):
    def make(n):
        for i in range(n):
            hid = services.get_or_create_handle("x", f"acct{i}{n}")
            SocialProfile.objects.create(user=user, handle_id=hid)

    make(1)
    with CaptureQueriesContext(connection) as small:
        services.list_profile_summaries(user.pk)
    make(6)
    with CaptureQueriesContext(connection) as big:
        services.list_profile_summaries(user.pk)
        services.list_profiles(user.pk)
    assert (
        len(big) <= len(small) + 2
    )  # list_profiles adds 2; nothing scales with the rows


def test_get_or_create_profile_is_idempotent(user):
    first, created = services.get_or_create_profile(user.pk, "x", "@Nuevo")
    again, created_again = services.get_or_create_profile(user.pk, "x", "nuevo")
    assert (first, created, created_again) == (again, True, False)


def test_mark_bootstrapped_is_true_once(profile_id):
    assert services.mark_bootstrapped(profile_id) is True
    assert services.mark_bootstrapped(profile_id) is False


# ------------------------------------------------------------------ posts


def test_upsert_inserts_then_updates_idempotently(handle_id):
    first = services.upsert_posts(handle_id, [post_in("1"), post_in("2")])
    assert (first.inserted, first.updated, len(first.post_ids)) == (2, 0, 2)
    again = services.upsert_posts(handle_id, [post_in("1"), post_in("2")])
    assert (again.inserted, again.updated) == (0, 2)
    assert again.post_ids == first.post_ids
    assert Post.objects.count() == 2


def test_upsert_batch_with_repeats_keeps_the_last(handle_id):
    result = services.upsert_posts(
        handle_id, [post_in("1", text="a"), post_in("1", text="b")]
    )
    assert len(result.post_ids) == 1
    assert Post.objects.get().caption == "b"


def test_upsert_empty_is_a_noop(handle_id):
    assert services.upsert_posts(handle_id, []) == services.UpsertResult(0, 0, ())


def test_null_never_overwrites_known_values(handle_id):
    services.upsert_posts(
        handle_id,
        [
            post_in(
                "1",
                url="http://x/1",
                source="pfm",
                metrics=PostMetrics(views=100, likes=7),
            )
        ],
    )
    services.upsert_posts(
        handle_id,
        [PostIn(platform="x", external_id="1", text="", published_at=None, kind=None)],
    )
    post = Post.objects.get()
    assert post.published_at == T0
    assert (post.caption, post.url, post.source, post.kind) == (
        "post 1",
        "http://x/1",
        "pfm",
        "original",
    )
    assert MetricSnapshot.objects.count() == 1


def test_snapshot_only_when_metrics_change_and_nulls_carry_forward(handle_id):
    services.upsert_posts(
        handle_id, [post_in("1", metrics=PostMetrics(views=100, likes=7))]
    )
    services.upsert_posts(
        handle_id, [post_in("1", metrics=PostMetrics(views=100, likes=7))]
    )
    assert MetricSnapshot.objects.count() == 1
    services.upsert_posts(handle_id, [post_in("1", metrics=PostMetrics(likes=9))])
    newest = MetricSnapshot.objects.order_by("-captured_at").first()
    assert (newest.likes, newest.views) == (9, 100)  # views carried forward, never 0
    assert MetricSnapshot.objects.count() == 2


def test_no_metrics_means_no_snapshot(handle_id):
    services.upsert_posts(handle_id, [post_in("1")])
    assert MetricSnapshot.objects.count() == 0


def test_typed_kind_corrects_a_stored_kind(handle_id):
    services.upsert_posts(handle_id, [post_in("1", kind=None)])
    assert Post.objects.get().kind == "original"
    services.upsert_posts(handle_id, [post_in("1", kind="reply")])
    assert Post.objects.get().kind == "reply"


def test_media_is_replaced_by_position(handle_id):
    services.upsert_posts(
        handle_id,
        [post_in("1", media=(MediaRef("image", "u0"), MediaRef("video", "u1")))],
    )
    services.upsert_posts(handle_id, [post_in("1", media=(MediaRef("gif", "n0"),))])
    media = list(
        Post.objects.get().media.order_by("position").values_list("kind", "url")
    )
    assert media == [("gif", "n0"), ("video", "u1")]


def test_media_with_unknown_kind_is_stored_as_null(handle_id, profile_id):
    """Ports 1.9: ``MediaRef(kind=None)`` means "type unknown". It is stored, never guessed."""
    services.upsert_posts(
        handle_id,
        [
            post_in(
                "1", media=(MediaRef(None, "https://x/a.jpg"), MediaRef("video", "v"))
            )
        ],
    )
    media = list(
        Post.objects.get().media.order_by("position").values_list("kind", "url")
    )
    assert media == [(None, "https://x/a.jpg"), ("video", "v")]
    out = services.list_posts(profile_id)[0]
    assert [(m.kind, m.url) for m in out.media] == [
        (None, "https://x/a.jpg"),
        ("video", "v"),
    ]


def test_media_with_an_invalid_kind_is_still_rejected(handle_id):
    with pytest.raises(IntegrityError), transaction.atomic():
        services.upsert_posts(
            handle_id, [post_in("1", media=(MediaRef("audio", "u"),))]
        )
    assert not PostMedia.objects.exists()


def test_stub_becomes_a_post_on_upsert(handle_id):
    Post.objects.create(author_id=handle_id, platform_post_id="9", is_stub=True)
    services.upsert_posts(handle_id, [post_in("9")])
    assert Post.objects.get().is_stub is False


def test_peer_posts_are_accepted(handle_id):
    peer = PeerPostIn(
        platform="x",
        external_id="p1",
        author_handle="peer",
        text="hey",
        metrics=PostMetrics(likes=3),
    )
    assert services.upsert_posts(handle_id, [peer]).inserted == 1


def test_list_posts_originals_newest_first_with_latest_metrics(profile_id, handle_id):
    services.upsert_posts(
        handle_id,
        [
            post_in("1", published_at=T0, metrics=PostMetrics(views=5)),
            post_in(
                "2", published_at=T0 + timedelta(hours=1), metrics=PostMetrics(views=8)
            ),
            post_in("3", kind="reply", published_at=T0 + timedelta(hours=2)),
        ],
    )
    out = services.list_posts(profile_id)
    assert [p.external_id for p in out] == ["2", "1"]
    assert out[0].metrics.views == 8
    assert out[0].profile_id == profile_id
    assert out[0].author_handle == "ateh"
    assert [
        p.external_id for p in services.list_posts(profile_id, kinds=["reply"])
    ] == ["3"]
    assert services.list_posts(profile_id, platform="linkedin") == []
    assert [
        p.external_id
        for p in services.list_posts(profile_id, since=T0 + timedelta(minutes=30))
    ] == ["2"]
    assert len(services.list_posts(profile_id, limit=1)) == 1


def test_list_posts_hides_deleted_suspects_unless_asked(profile_id, handle_id):
    services.upsert_posts(handle_id, [post_in("1"), post_in("2")])
    Post.objects.filter(platform_post_id="2").update(is_deleted_suspect=True)
    assert [p.external_id for p in services.list_posts(profile_id)] == ["1"]
    assert len(services.list_posts(profile_id, include_deleted=True)) == 2


def test_list_posts_query_count_is_constant(profile_id, handle_id):
    def seed(n):
        services.upsert_posts(
            handle_id,
            [
                post_in(
                    f"{n}-{i}",
                    metrics=PostMetrics(views=i + 1),
                    media=(MediaRef("image", "u"),),
                )
                for i in range(n)
            ],
        )

    seed(2)
    with CaptureQueriesContext(connection) as small:
        services.list_posts(profile_id)
    seed(30)
    with CaptureQueriesContext(connection) as big:
        services.list_posts(profile_id, limit=200)
    assert len(big) == len(small)


def test_get_posts_keeps_order_and_labels_foreign_posts_zero(profile_id, handle_id):
    services.upsert_posts(handle_id, [post_in("1"), post_in("2")])
    peer = services.get_or_create_handle("x", "peer")
    [peer_post] = services.upsert_posts(peer, [post_in("p")]).post_ids
    mine = list(
        Post.objects.filter(author_id=handle_id)
        .order_by("-id")
        .values_list("id", flat=True)
    )
    out = services.get_posts([*mine, peer_post, 999999])
    assert [p.id for p in out] == [*mine, peer_post]
    assert [p.profile_id for p in out] == [profile_id, profile_id, 0]
    assert (
        services.get_posts([peer_post], profile_id=profile_id)[0].profile_id
        == profile_id
    )
    assert services.get_posts([]) == []


def test_list_activity_returns_replies_and_retweets(profile_id, handle_id):
    services.upsert_posts(
        handle_id,
        [
            post_in("1"),
            post_in("2", kind="reply"),
            post_in("3", kind="retweet", published_at=T0 + timedelta(hours=1)),
        ],
    )
    assert [a.kind for a in services.list_activity(profile_id)] == ["retweet", "reply"]
    assert [a.kind for a in services.list_activity(profile_id, kind="reply")] == [
        "reply"
    ]


def test_append_metric_snapshots_ignores_repeats(handle_id):
    [pid] = services.upsert_posts(handle_id, [post_in("1")]).post_ids
    snap = services.SnapshotIn(T0, PostMetrics(views=1, likes=2), "xpoz")
    services.append_metric_snapshots(pid, [snap])
    services.append_metric_snapshots(pid, [snap])
    assert MetricSnapshot.objects.filter(post_id=pid).count() == 1


# ------------------------------------------------------------------ baseline


def test_baseline_is_insert_only_and_latest_wins(profile_id):
    assert services.latest_baseline(profile_id) is None

    def baseline(n, at):
        return BaselineOut(profile_id, 90, n, 1.0, 2.0, 3.0, True, at)

    services.save_baseline(baseline(5, T0))
    services.save_baseline(baseline(9, T0 + timedelta(days=1)))
    services.save_baseline(baseline(7, T0 - timedelta(days=1)))
    assert services.latest_baseline(profile_id).n_posts == 9
    assert services.latest_baseline(profile_id).reliable is True


# ------------------------------------------------------------------ alerts and matches


@pytest.fixture
def a_post(handle_id):
    return services.upsert_posts(handle_id, [post_in("1")]).post_ids[0]


def test_create_alert_once_dedupes_active_alerts_and_allows_after_dismissal(
    profile_id, a_post
):
    assert services.create_alert_once(
        profile_id,
        a_post,
        "spike",
        trigger="velocity",
        velocity=3.0,
        baseline_velocity=1.0,
    )
    assert not services.create_alert_once(profile_id, a_post, "spike")
    assert services.create_alert_once(
        profile_id, a_post, "niche_match"
    )  # other kind is separate
    [alert] = [a for a in services.unread_alerts(profile_id) if a.kind == "spike"]
    assert services.dismiss_alert(profile_id, alert.id) is True
    assert services.create_alert_once(profile_id, a_post, "spike")
    assert Alert.objects.filter(post_id=a_post, kind="spike").count() == 2


def test_unread_alert_details_and_dismiss(profile_id, a_post):
    services.create_alert_once(profile_id, a_post, "spike", velocity=2.5)
    [detail] = services.unread_alert_details(profile_id)
    assert detail["caption"] == "post 1"
    assert detail["platform_post_id"] == "1"
    assert (detail["velocity"], detail["baseline_velocity"], detail["kind"]) == (
        2.5,
        None,
        "spike",
    )
    assert services.dismiss_alert(profile_id, detail["id"]) is True
    assert services.dismiss_alert(profile_id, detail["id"]) is True  # twice is fine
    assert services.unread_alert_details(profile_id) == []
    assert Alert.objects.get().dismissed_at is not None
    assert services.dismiss_alert(profile_id, 424242) is False


def test_dismiss_refuses_an_alert_of_another_profile(user, profile_id, a_post):
    services.create_alert_once(profile_id, a_post, "spike")
    other = SocialProfile.objects.create(
        user=user, handle_id=services.get_or_create_handle("x", "second")
    ).pk
    alert_id = Alert.objects.get().pk
    assert services.dismiss_alert(other, alert_id) is False
    assert Alert.objects.get().status == "active"


def test_record_listening_match_is_true_once(profile_id, a_post):
    assert services.record_listening_match(profile_id, a_post, 0.5) is True
    assert services.record_listening_match(profile_id, a_post) is False


# ------------------------------------------------------------------ listening config


def test_listening_defaults_to_disabled(profile_id):
    config = services.get_listening(profile_id)
    assert (config.keywords, config.enabled, config.interval_minutes) == (
        (),
        False,
        None,
    )


def test_set_listening_replaces_the_keyword_set(profile_id):
    services.set_listening(
        ListeningConfig(profile_id, ("AI", " ai ", "cats", ""), True, 15)
    )
    config = services.get_listening(profile_id)
    assert (config.keywords, config.enabled, config.interval_minutes) == (
        ("AI", "cats"),
        True,
        15,
    )
    kept_id = ListeningKeyword.objects.get(keyword="cats").pk
    services.set_listening(ListeningConfig(profile_id, ("Cats", "dogs"), False, None))
    config = services.get_listening(profile_id)
    assert config.keywords == (
        "cats",
        "dogs",
    )  # the existing row keeps its spelling and id
    assert ListeningKeyword.objects.get(keyword="cats").pk == kept_id
    assert (config.enabled, config.interval_minutes) == (False, 15)


@pytest.mark.parametrize("interval", [0, 1441, -3])
def test_set_listening_rejects_a_bad_interval(profile_id, interval):
    with pytest.raises(ValueError, match="interval_minutes"):
        services.set_listening(ListeningConfig(profile_id, (), True, interval))


def test_set_listening_is_atomic_when_a_keyword_is_invalid(profile_id):
    services.set_listening(ListeningConfig(profile_id, ("keep",), True, 5))
    with pytest.raises(ValueError, match="keyword"):
        services.set_listening(ListeningConfig(profile_id, ("x" * 101,), False, 9))
    config = services.get_listening(profile_id)
    assert (config.keywords, config.enabled, config.interval_minutes) == (
        ("keep",),
        True,
        5,
    )


# ------------------------------------------------------------------ polls


def only_these_polls(*profile_ids):
    """Switch off every poll config that is not one of ``profile_ids``.

    ``claim_due_polls`` is global by design: it claims any due row in the table. A committed row
    from another session (a parallel pytest run on the same Postgres, or a crashed one) would
    take a slot and break an exact assertion. The tests that count claims call this first so
    they only see their own rows. Rows another session holds locked are skipped, not waited for.
    """
    with transaction.atomic():
        foreign = list(
            PollConfig.objects.select_for_update(skip_locked=True)
            .filter(is_active=True)
            .exclude(profile_id__in=profile_ids)
            .values_list("pk", flat=True)
        )
        PollConfig.objects.filter(pk__in=foreign).update(is_active=False)


def test_claim_due_polls_claims_each_profile_once(user, profile_id):
    other = SocialProfile.objects.create(
        user=user, handle_id=services.get_or_create_handle("x", "second")
    ).pk
    services.set_listening(ListeningConfig(profile_id, (), True, 5))
    services.set_listening(ListeningConfig(other, (), False, 5))
    only_these_polls(profile_id)
    assert services.claim_due_polls() == [profile_id]
    assert services.claim_due_polls() == []  # just claimed
    PollConfig.objects.filter(profile_id=profile_id).update(
        last_polled_at=timezone.now() - timedelta(minutes=6)
    )
    assert services.claim_due_polls() == [profile_id]


def test_claim_due_polls_respects_the_limit(user):
    ids = []
    for i in range(3):
        pid = SocialProfile.objects.create(
            user=user, handle_id=services.get_or_create_handle("x", f"p{i}")
        ).pk
        services.set_listening(ListeningConfig(pid, (), True, 5))
        ids.append(pid)
    only_these_polls(*ids)
    assert len(services.claim_due_polls(limit=2)) == 2
    assert len(services.claim_due_polls(limit=2)) == 1


def test_a_foreign_due_row_takes_a_slot_unless_the_helper_switches_it_off(user):
    """Pins the cause of the intermittent failure: ``claim_due_polls`` is global."""
    pids = []
    for i in range(3):
        pid = SocialProfile.objects.create(
            user=user, handle_id=services.get_or_create_handle("x", f"q{i}")
        ).pk
        services.set_listening(ListeningConfig(pid, (), True, 5))
        pids.append(pid)
    *mine, foreign = pids  # ``foreign`` stands for a row another session committed
    assert services.claim_due_polls(limit=3) == sorted(
        pids
    )  # it is claimed like any other
    PollConfig.objects.update(last_polled_at=None)
    only_these_polls(*mine)
    assert services.claim_due_polls(limit=3) == sorted(mine)
    assert not PollConfig.objects.get(profile_id=foreign).is_active


@pytest.mark.django_db(transaction=True)
def test_two_workers_never_claim_the_same_profile():
    user = User.objects.create_user("race@example.com")
    mine: list[int] = []
    for i in range(20):
        pid = SocialProfile.objects.create(
            user=user, handle_id=services.get_or_create_handle("x", f"r{i}")
        ).pk
        services.set_listening(ListeningConfig(pid, (), True, 5))
        mine.append(pid)
    only_these_polls(*mine)
    claimed: list[list[int]] = []
    barrier = threading.Barrier(2)

    def worker():
        try:
            barrier.wait()
            claimed.append(services.claim_due_polls(limit=20))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    flat = [pid for batch in claimed for pid in batch]
    assert len(flat) == len(set(flat)) == 20


# ------------------------------------------------------------------ async twins


@pytest.mark.django_db(transaction=True)
async def test_async_twins_match_the_sync_functions(user):
    try:
        pid, created = await services.aget_or_create_profile(user.pk, "x", "asyncy")
        info = await services.aget_profile(pid, user.pk)
        assert created
        assert info.handle == "asyncy"
        await sync_to_async(only_these_polls)()
        assert (await services.aclaim_due_polls()) == []
    finally:  # the worker thread of sync_to_async owns a connection; free it before teardown
        await sync_to_async(connections.close_all, thread_sensitive=True)()


# ------------------------------------------------------------------ analytics


def test_analytics_without_posts_is_empty_not_invented(profile_id):
    body = services.get_analytics(profile_id)
    assert body["is_live_data"] is False
    assert (body["total_impressions"], body["top_posts"], body["reach_series"]) == (
        0,
        [],
        [],
    )
    assert "ateh" in body["summary"]
    assert services.get_analytics(424242) is None


def test_analytics_counts_the_latest_snapshot_of_each_post_once(profile_id, handle_id):
    short = "word " * 5
    medium = "word " * 40
    services.upsert_posts(
        handle_id,
        [
            post_in(
                "1",
                text=short,
                metrics=PostMetrics(views=100, likes=10, comments=2, shares=1),
            ),
            post_in("2", text=medium, metrics=PostMetrics(views=300, likes=30)),
        ],
    )
    services.upsert_posts(
        handle_id, [post_in("1", text=short, metrics=PostMetrics(views=200, likes=15))]
    )
    body = services.get_analytics(profile_id)
    assert body["is_live_data"] is True
    assert body["total_impressions"] == 500  # 200 + 300, not 100 + 200 + 300
    assert (body["total_likes"], body["total_comments"]) == (45, 2)
    assert [a["pct"] for a in body["allocation"]] == [40.0, 60.0, 0.0]
    assert [p["impressions"] for p in body["top_posts"]] == [300, 200]
    assert len(body["reach_series"]) == 3
    assert body["reach_series"][0] == 0.0


def test_analytics_ignores_replies_and_other_authors(profile_id, handle_id):
    other = services.get_or_create_handle("x", "peer")
    services.upsert_posts(
        handle_id, [post_in("1", kind="reply", metrics=PostMetrics(views=999))]
    )
    services.upsert_posts(other, [post_in("2", metrics=PostMetrics(views=999))])
    assert services.get_analytics(profile_id)["is_live_data"] is False


def test_analytics_query_count_is_constant(profile_id, handle_id):
    services.upsert_posts(handle_id, [post_in("a", metrics=PostMetrics(views=5))])
    with CaptureQueriesContext(connection) as small:
        services.get_analytics(profile_id)
    services.upsert_posts(
        handle_id,
        [post_in(str(i), metrics=PostMetrics(views=i + 1)) for i in range(40)],
    )
    with CaptureQueriesContext(connection) as big:
        services.get_analytics(profile_id)
    assert len(big) == len(small)


def test_rank_posts_orders_in_database_and_omits_missing_metrics(profile_id, handle_id):
    services.upsert_posts(
        handle_id,
        [
            post_in(
                "rank-1", text="most likes", metrics=PostMetrics(views=20, likes=90)
            ),
            post_in(
                "rank-2", text="most views", metrics=PostMetrics(views=200, likes=10)
            ),
            post_in(
                "rank-old",
                text="old",
                published_at=T0 - timedelta(days=60),
                metrics=PostMetrics(views=900, likes=900),
            ),
            post_in("rank-none", text="unknown", metrics=None),
            post_in(
                "rank-reply", kind="reply", metrics=PostMetrics(views=9999, likes=9999)
            ),
        ],
    )
    views = services.rank_posts(
        profile_id, metric="views", since=T0 - timedelta(days=28)
    )
    assert [(row.post.text, row.value) for row in views] == [
        ("most views", 200),
        ("most likes", 20),
    ]

    likes = services.rank_posts(
        profile_id, metric="likes", since=T0 - timedelta(days=28)
    )
    assert [(row.post.text, row.value) for row in likes] == [
        ("most likes", 90),
        ("most views", 10),
    ]
    assert services.rank_posts(profile_id, metric="views", platform="instagram") == []
    with pytest.raises(ValueError, match="Unsupported post metric"):
        services.rank_posts(profile_id, metric="bookmarks")


# ------------------------------------------------------------------ threads


def test_rethread_numbers_by_publish_time_not_arrival(handle_id):
    services.upsert_posts(
        handle_id,
        [  # newest first, as ingest delivers them
            post_in("200", conversation_id="c1", published_at=T0),
            post_in("199", conversation_id="c1", published_at=T0 - timedelta(hours=1)),
            post_in("500", conversation_id="other", published_at=T0),
        ],
    )
    assert services.rethread_conversation(handle_id, "c1") == 2
    early = Post.objects.get(platform_post_id="199")
    late = Post.objects.get(platform_post_id="200")
    assert (early.thread_position, early.is_thread_head) == (1, True)
    assert (late.thread_position, late.is_thread_head) == (2, False)
    untouched = Post.objects.get(platform_post_id="500")
    assert (untouched.thread_position, untouched.is_thread_head) == (None, None)


def test_rethread_is_idempotent_and_ignores_a_blank_conversation(handle_id):
    services.upsert_posts(
        handle_id,
        [post_in("1", conversation_id="c1"), post_in("2", conversation_id="")],
    )
    assert services.rethread_conversation(handle_id, "c1") == 1
    with CaptureQueriesContext(connection) as queries:
        assert services.rethread_conversation(handle_id, "c1") == 1
    assert not [q for q in queries if q["sql"].lstrip().upper().startswith("UPDATE")]
    assert services.rethread_conversation(handle_id, "") == 0


# ------------------------------------------------------------------ last_checked_at


def test_an_unchanged_recheck_stamps_the_post_without_a_new_snapshot(handle_id):
    same = post_in("1", metrics=PostMetrics(views=100, likes=7))
    services.upsert_posts(handle_id, [same])
    first = Post.objects.get(platform_post_id="1")
    assert first.last_checked_at is not None
    Post.objects.filter(pk=first.pk).update(
        last_checked_at=T0 - timedelta(days=3)  # pretend the first check was long ago
    )
    services.upsert_posts(handle_id, [same])
    assert MetricSnapshot.objects.count() == 1
    again = Post.objects.get(pk=first.pk)
    assert again.last_checked_at > T0  # restamped by the second check


def test_a_changed_recheck_stamps_the_post_and_stores_a_snapshot(handle_id):
    services.upsert_posts(handle_id, [post_in("1", metrics=PostMetrics(likes=7))])
    Post.objects.update(last_checked_at=T0)
    services.upsert_posts(handle_id, [post_in("1", metrics=PostMetrics(likes=9))])
    assert MetricSnapshot.objects.count() == 2
    assert Post.objects.get().last_checked_at > T0


def test_a_post_that_came_without_metrics_is_not_marked_as_checked(handle_id):
    services.upsert_posts(handle_id, [post_in("1")])
    assert Post.objects.get().last_checked_at is None
    services.upsert_posts(handle_id, [post_in("1", metrics=PostMetrics())])
    assert Post.objects.get().last_checked_at is None


def test_explicit_readings_move_the_stamp_forward_but_never_back(handle_id):
    services.upsert_posts(handle_id, [post_in("1")])
    pid = Post.objects.get().pk
    late = T0 + timedelta(hours=5)
    services.append_metric_snapshots(
        pid, [services.SnapshotIn(captured_at=late, metrics=PostMetrics(likes=1))]
    )
    assert Post.objects.get().last_checked_at == late
    services.append_metric_snapshots(
        pid, [services.SnapshotIn(captured_at=T0, metrics=PostMetrics(likes=2))]
    )
    assert Post.objects.get().last_checked_at == late
