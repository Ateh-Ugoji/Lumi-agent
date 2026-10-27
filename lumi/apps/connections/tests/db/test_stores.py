"""The Django stores against Postgres. Sync tests drive the async ports with ``async_to_sync``."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from asgiref.sync import async_to_sync
from django.db import connection, connections

from apps.connections.clients.credits import CreditEntry
from apps.connections.config import ConnectionsConfig
from apps.connections.errors import ProviderAuthError, ProviderUnavailable
from apps.connections.handles.service import HandleSearch
from apps.connections.handles.types import CacheEntry, HandleRow
from apps.connections.models import (
    HandleSearchCache,
    OAuthState,
    PublishJob,
    XpozCreditLedger,
)
from apps.connections.oauth import OAuthStateRecord
from apps.connections.providers.base import AccountInfo, PublishDraft, TokenSet
from apps.connections.providers.registry import build_provider
from apps.connections.publishing import Publisher, PublishInProgress
from apps.connections.stores import (
    DjangoCreditLedger,
    DjangoHandleStore,
    DjangoOAuthStateStore,
    DjangoPublishLedger,
    normalize_handle,
    purge_expired_states,
)
from apps.profiles.models import SocialHandle

from ..fakes import Recorder
from ..handles.fakes import Clock, ScriptedLive

pytestmark = pytest.mark.django_db

CALLBACK = "http://localhost:8000/api/v1/connections/{}/callback"


def redirect_uri_for(provider: str) -> str:
    return CALLBACK.format(provider)


def record(user, state="state-1", provider="x", minutes=10, verifier="VERIFIER-1"):
    return OAuthStateRecord(
        state=state,
        provider=provider,
        user_id=user.pk,
        redirect_uri="ignored",
        redirect_after="/settings",
        expires_at=datetime.now(UTC) + timedelta(minutes=minutes),
        code_verifier=verifier,
    )


# --- OAuth state ---------------------------------------------------------------------------


def test_state_is_used_once_and_returns_the_decrypted_verifier(user) -> None:
    store = DjangoOAuthStateStore(redirect_uri_for)
    async_to_sync(store.save)(record(user))
    (stored,) = [r[0] for r in _raw("SELECT code_verifier FROM oauth_states")]
    assert "VERIFIER" not in stored

    first = async_to_sync(store.consume)("state-1", "x")
    assert first is not None
    assert first.user_id == user.pk and first.code_verifier == "VERIFIER-1"
    assert first.redirect_after == "/settings"
    assert first.redirect_uri == redirect_uri_for("x")
    assert async_to_sync(store.consume)("state-1", "x") is None


def test_unknown_expired_and_other_provider_states_are_refused(user) -> None:
    store = DjangoOAuthStateStore(redirect_uri_for)
    async_to_sync(store.save)(record(user, "fresh", "linkedin"))
    async_to_sync(store.save)(record(user, "old", "x", minutes=-1))
    assert async_to_sync(store.consume)("nope", "x") is None
    assert async_to_sync(store.consume)("old", "x") is None
    # A callback of another provider neither works nor burns the state.
    assert async_to_sync(store.consume)("fresh", "x") is None
    assert async_to_sync(store.consume)("fresh", "linkedin") is not None


def test_a_state_without_a_verifier_comes_back_as_none(user) -> None:
    store = DjangoOAuthStateStore(redirect_uri_for)
    async_to_sync(store.save)(record(user, verifier=None))
    got = async_to_sync(store.consume)("state-1", "x")
    assert got is not None and got.code_verifier is None


def test_expired_and_used_states_are_purged(user) -> None:
    store = DjangoOAuthStateStore(redirect_uri_for)
    async_to_sync(store.save)(record(user, "live"))
    async_to_sync(store.save)(record(user, "used"))
    async_to_sync(store.save)(record(user, "gone", minutes=-5))
    async_to_sync(store.consume)("used", "x")
    assert purge_expired_states() == 2
    assert list(OAuthState.objects.values_list("state", flat=True)) == ["live"]


@pytest.mark.django_db(transaction=True)
def test_two_callbacks_cannot_both_win(user) -> None:
    store = DjangoOAuthStateStore(redirect_uri_for)
    async_to_sync(store.save)(record(user))
    start = threading.Barrier(8)
    winners: list[object] = []
    lock = threading.Lock()

    def callback() -> None:
        try:
            start.wait(timeout=10)
            got = store._consume("state-1", "x")
            with lock:
                winners.append(got)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=callback) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(winners) == 8
    assert sum(w is not None for w in winners) == 1


def _raw(sql: str):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


# --- Publishing ----------------------------------------------------------------------------

TOKENS = TokenSet(access_token="li-access-FAKE", scopes=("w_member_social",))
ACCOUNT = AccountInfo(external_id="782bbtaQ", display_name="Christian")
CONFIG = ConnectionsConfig.from_env({})


def publisher_for(profile, handler):
    rec = Recorder(handler)
    provider = build_provider("linkedin", CONFIG, transport=rec.transport)
    ledger = DjangoPublishLedger(platform="linkedin", text="hola")
    return provider, Publisher(ledger), rec


def publish(publisher, provider, profile, **kwargs):
    kwargs.setdefault("confirm", True)
    kwargs.setdefault("idempotency_key", "k1")
    return async_to_sync(publisher.publish)(
        provider, TOKENS, ACCOUNT, PublishDraft(text="hola"), scope=profile.pk, **kwargs
    )


def created(request: httpx.Request) -> httpx.Response:
    return httpx.Response(201, headers={"x-restli-id": "urn:li:share:1"})


def test_publish_is_stored_and_a_repeat_replays_without_a_second_post(profile) -> None:
    provider, publisher, rec = publisher_for(profile, created)
    first = publish(publisher, provider, profile)
    again = publish(publisher, provider, profile)
    assert not first.replayed and again.replayed
    assert again.result.external_post_id == "urn:li:share:1"
    assert len(rec.requests) == 1
    job = PublishJob.objects.get()
    assert job.status == "done" and job.external_post_id == "urn:li:share:1"
    assert len(job.fingerprint) == 64 and job.error == ""


def test_dry_run_leaves_no_row(profile) -> None:
    provider, publisher, rec = publisher_for(profile, created)
    result = publish(publisher, provider, profile, dry_run=True, confirm=False)
    assert result.result.dry_run and PublishJob.objects.count() == 0
    assert rec.requests == []


def test_definite_failure_is_stored_with_its_reason_and_can_be_retried(
    profile,
) -> None:
    answers = iter([httpx.Response(401), created(None)])
    provider, publisher, _rec = publisher_for(profile, lambda r: next(answers))
    with pytest.raises(ProviderAuthError):
        publish(publisher, provider, profile)
    job = PublishJob.objects.get()
    assert job.status == "failed" and job.error.startswith("ProviderAuthError")
    assert "FAKE" not in job.error and "://" not in job.error

    retried = publish(publisher, provider, profile)
    assert not retried.replayed and retried.result.external_post_id == "urn:li:share:1"
    job.refresh_from_db()
    assert job.status == "done" and job.error == ""
    assert PublishJob.objects.count() == 1


def test_an_outage_leaves_the_job_unknown_and_blocks_a_blind_retry(profile) -> None:
    provider, publisher, rec = publisher_for(profile, lambda r: httpx.Response(503))
    with pytest.raises(ProviderUnavailable):
        publish(publisher, provider, profile)
    assert PublishJob.objects.get().status == "unknown"
    with pytest.raises(PublishInProgress):
        publish(publisher, provider, profile)
    assert len(rec.requests) == 1


def test_only_one_retry_can_claim_a_failed_job(profile) -> None:
    ledger = DjangoPublishLedger(platform="linkedin", text="hola")
    async_to_sync(ledger.begin)(profile.pk, "k", "a" * 64)
    async_to_sync(ledger.finish)(profile.pk, "k", "failed", error="boom")
    async_to_sync(ledger.restart)(profile.pk, "k")
    with pytest.raises(PublishInProgress):
        async_to_sync(ledger.restart)(profile.pk, "k")


def test_finish_only_closes_a_pending_job(profile) -> None:
    ledger = DjangoPublishLedger(platform="linkedin", text="hola")
    async_to_sync(ledger.begin)(profile.pk, "k", "a" * 64)
    async_to_sync(ledger.finish)(profile.pk, "k", "unknown", error="net")
    async_to_sync(ledger.finish)(profile.pk, "k", "done")  # late, must not overwrite
    assert PublishJob.objects.get().status == "unknown"


# --- Credits -------------------------------------------------------------------------------


def test_credit_entries_are_recorded_by_slot_never_by_key(user) -> None:
    ledger = DjangoCreditLedger(user_id=user.pk)
    entry = CreditEntry(
        provider="xpoz",
        route="x.users.search",
        credits=2,
        key_slot=2,
        at=datetime.now(UTC),
        run_id="run-1",
    )
    async_to_sync(ledger.record)(entry)
    row = XpozCreditLedger.objects.get()
    assert (row.user_id, row.route, row.credits, row.key_slot, row.run_id) == (
        user.pk,
        "x.users.search",
        2,
        2,
        "run-1",
    )


def test_credit_entries_without_a_user_are_allowed(db) -> None:
    async_to_sync(DjangoCreditLedger().record)(
        CreditEntry("xpoz", "x.users.search", 2, 1, datetime.now(UTC))
    )
    assert XpozCreditLedger.objects.get().user_id is None


# --- Handles -------------------------------------------------------------------------------


def test_handles_are_normalized_and_unsafe_ones_are_dropped() -> None:
    assert normalize_handle("@KarPathy ") == "karpathy"
    assert normalize_handle("dr.who_1-x") == "dr.who_1-x"
    assert normalize_handle("two words") is None
    assert normalize_handle("") is None
    assert normalize_handle("a" * 101) is None
    assert normalize_handle("ñandú") is None


def row(handle, platform="x", followers=None, name="", avatar="", source="live"):
    return HandleRow(handle, platform, name, avatar, followers, source)


def test_cache_entry_round_trips_in_order_with_handle_data(db) -> None:
    store = DjangoHandleStore()
    when = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    rows = (
        row("KarPathy", followers=1_000_000, name="Andrej"),
        row("karen", followers=None),
    )
    async_to_sync(store.put_entry)(CacheEntry("x", "kar", when, rows))
    async_to_sync(store.remember_live)(list(rows))

    (entry,) = async_to_sync(store.related_entries)("x", "kar")
    assert entry.fetched_at == when and entry.query == "kar"
    assert [r.handle for r in entry.rows] == ["KarPathy", "karen"]
    assert entry.rows[0].followers == 1_000_000 and entry.rows[1].followers is None


def test_related_entries_follow_the_prefix_chain_both_ways(db) -> None:
    store = DjangoHandleStore()
    when = datetime(2026, 10, 27, tzinfo=UTC)
    for q in ("ka", "karp", "zz"):
        async_to_sync(store.put_entry)(CacheEntry("x", q, when, ()))
    async_to_sync(store.put_entry)(CacheEntry("tiktok", "kar", when, ()))
    got = {e.query for e in async_to_sync(store.related_entries)("x", "kar")}
    assert got == {"ka", "karp"}


def test_replacing_an_entry_replaces_its_rows(db) -> None:
    store = DjangoHandleStore()
    when = datetime(2026, 10, 27, tzinfo=UTC)
    async_to_sync(store.put_entry)(
        CacheEntry("x", "kar", when, (row("one"), row("two")))
    )
    async_to_sync(store.put_entry)(CacheEntry("x", "kar", when, (row("three"),)))
    (entry,) = async_to_sync(store.related_entries)("x", "kar")
    assert [r.handle for r in entry.rows] == ["three"]
    assert HandleSearchCache.objects.count() == 1


def test_a_missing_follower_count_never_wipes_a_known_one(db) -> None:
    store = DjangoHandleStore()
    async_to_sync(store.remember_live)([row("karpathy", followers=900, name="Andrej")])
    async_to_sync(store.remember_live)([row("karpathy", followers=None, name="")])
    handle = SocialHandle.objects.get(handle_normalized="karpathy")
    assert handle.follower_count == 900 and handle.display_name == "Andrej"


def test_remember_new_keeps_what_is_already_known(db) -> None:
    store = DjangoHandleStore()
    async_to_sync(store.remember_live)([row("karpathy", followers=900)])
    async_to_sync(store.remember_new)(
        [row("karpathy", followers=5, source="cache"), row("fresh", source="cache")]
    )
    assert SocialHandle.objects.get(handle_normalized="karpathy").follower_count == 900
    assert SocialHandle.objects.get(handle_normalized="fresh").origin == "cache"
    assert async_to_sync(store.known_keys)("x", ["KarPathy", "ghost"]) == {"x:karpathy"}


def test_a_live_row_upgrades_the_origin_but_never_downgrades_selected(db) -> None:
    store = DjangoHandleStore()
    async_to_sync(store.remember_new)([row("a", source="cache")])
    SocialHandle.objects.create(
        platform="x", handle_normalized="b", origin="selected", follower_count=1
    )
    async_to_sync(store.remember_live)([row("a", followers=3), row("b", followers=4)])
    assert SocialHandle.objects.get(handle_normalized="a").origin == "live"
    assert SocialHandle.objects.get(handle_normalized="b").origin == "selected"


def test_unsafe_handles_never_reach_the_table(db) -> None:
    store = DjangoHandleStore()
    when = datetime(2026, 10, 27, tzinfo=UTC)
    bad = [row("two words"), row("ok_one"), row("ñandú")]
    async_to_sync(store.put_entry)(CacheEntry("x", "ok", when, tuple(bad)))
    async_to_sync(store.remember_live)(bad)
    assert list(SocialHandle.objects.values_list("handle_normalized", flat=True)) == [
        "ok_one"
    ]


def test_profile_handles_and_remembered_are_scoped_by_platform_and_prefix(
    profile,
) -> None:
    store = DjangoHandleStore()
    async_to_sync(store.remember_live)(
        [row("karpathy", followers=9), row("kara", platform="instagram")]
    )
    assert async_to_sync(store.profile_handles)("linkedin", "m") == ["me"]
    assert async_to_sync(store.profile_handles)("x", "m") == []
    names = [r.handle for r in async_to_sync(store.remembered)("x", "kar")]
    assert names == ["karpathy"]


def test_search_pays_once_and_the_second_search_comes_from_postgres(db) -> None:
    clock = Clock()
    live = ScriptedLive({"x": [row("karpathy", followers=9, name="Andrej")]})
    search = HandleSearch(DjangoHandleStore(), live, ttl_minutes=60, clock=clock)

    first = async_to_sync(search.search)("karp", platforms="x")
    second = async_to_sync(search.search)("karp", platforms="x")
    assert [r.handle for r in first.results] == ["karpathy"] and first.live
    assert [r.handle for r in second.results] == ["karpathy"] and not second.live
    assert len(live.calls) == 1

    clock.advance(minutes=61)
    async_to_sync(search.search)("karp", platforms="x")
    assert len(live.calls) == 2


def test_a_failed_live_call_is_not_cached(db) -> None:
    clock = Clock()
    live = ScriptedLive(error=ProviderUnavailable("down", provider="xpoz"))
    search = HandleSearch(DjangoHandleStore(), live, ttl_minutes=60, clock=clock)
    result = async_to_sync(search.search)("karp", platforms="x")
    assert result.reason == "provider_unavailable"
    assert HandleSearchCache.objects.count() == 0
