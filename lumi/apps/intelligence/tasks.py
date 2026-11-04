"""Background jobs of the AI side. Registered when the app starts (``apps.py``).

Both read the profile's own posts first through ``wiring.post_sync`` (CONNECT's
``DjangoOwnPostSync``: the connected account's feed into Postgres).

``profile.bootstrap`` prepares a new profile for the agent: it syncs the posts, indexes them for
retrieval and learns the voice. A profile with no connected account (or a feed that cannot be
read) is not an error here: it finishes with ``voice = needs_style_questions`` and the user
answers the style questions instead; the result says ``sync = unavailable``.

``profile.refresh`` (``POST /profiles/{id}/refresh``) is the same sync on demand plus the
re-index. The user asked for it, so a feed that cannot be read fails the job.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from asgiref.sync import async_to_sync

from apps.core import jobs
from apps.core.jobs import JobContext, JobError
from apps.intelligence.repos.aio import aio
from apps.profiles import services
from lumi_ai.ports import SocialDataError

log = logging.getLogger(__name__)

BOOTSTRAP_KIND = "profile.bootstrap"
REFRESH_KIND = "profile.refresh"
PROGRESS_SYNCED = 20
PROGRESS_INDEXED = 40
PROGRESS_VOICE = 90

NICHE_PROMPT = (
    "You are an expert social media strategist. Analyze the creator's handle, "
    "display name, platform, and recent post captions to determine their specific content niche "
    "and 3 to 5 focused search keywords/hashtags for competitor discovery in that exact domain. "
    "Do not include unrelated topics or celebrities. "
    "Return strict JSON with this exact shape:\n"
    '{"title": "<concise niche title>", "keywords": ["keyword1", "keyword2", "keyword3"]}'
)


@jobs.register(BOOTSTRAP_KIND)
def bootstrap_profile(ctx: JobContext) -> dict[str, Any]:
    if ctx.profile_id is None:
        raise JobError("validation_error", "El trabajo no trae un perfil.")
    from apps.intelligence.wiring import begin_run, get_wiring

    wiring = get_wiring()
    profile_id = ctx.profile_id
    begin_run(profile_id)

    synced = _sync(wiring, profile_id)
    jobs.set_progress(ctx.id, PROGRESS_SYNCED)

    posts = async_to_sync(wiring.posts.list_posts)(
        profile_id, limit=wiring.config.voice_corpus_limit
    )
    try:
        indexed = wiring.indexer.index_posts(posts)
    except Exception as exc:  # noqa: BLE001
        log.warning("post indexing failed: %s; attempting reset of voice_corpus and retrying", exc)
        try:
            wiring.vectors.reset("voice_corpus")
            indexed = wiring.indexer.index_posts(posts)
        except Exception as retry_exc:  # noqa: BLE001
            log.warning("retry post indexing failed: %s", retry_exc)
            indexed = 0
    jobs.set_progress(ctx.id, PROGRESS_INDEXED)

    refreshed = async_to_sync(wiring.style.ensure_voice)(profile_id)
    jobs.set_progress(ctx.id, PROGRESS_VOICE)
    if refreshed.status == "failed":
        log.warning(
            "voice bootstrap failed for profile %s: %s", profile_id, refreshed.reason
        )
        raise JobError(
            "voice.learn_failed",
            "No se pudo aprender tu voz. Se puede reintentar más tarde.",
        )
    if refreshed.status == "needs_style_questions":
        inherited = _inherit_anchor_voice_if_available(profile_id)
        if inherited:
            refreshed = inherited

    niche_info = async_to_sync(_ensure_niche_and_competitors)(wiring, profile_id, posts)

    services.mark_bootstrapped(profile_id)
    res: dict[str, Any] = {
        "sync": "ok" if synced is not None else "unavailable",
        "posts_synced": synced["stored"] if synced else 0,
        "posts_indexed": indexed,
        "voice": refreshed.status,
        "posts_found": refreshed.posts_found,
    }
    if niche_info and niche_info.get("niche"):
        res["niche"] = niche_info.get("niche")
        res["competitors"] = niche_info.get("competitors", [])
        if niche_info.get("report_id"):
            res["report_id"] = niche_info.get("report_id")
    return res


async def _infer_niche(
    wiring: Any,
    *,
    handle: str,
    display_name: str,
    platform: str,
    posts: Sequence[Any],
) -> tuple[str, list[str]]:
    captions = [
        getattr(p, "text", "") or getattr(p, "caption", "")
        for p in posts
        if getattr(p, "text", "") or getattr(p, "caption", "")
    ]

    # 1. LLM extraction if chain providers exist
    if getattr(wiring, "chain", None) and getattr(wiring.chain, "providers", None):
        sample = "\n---\n".join(c[:300] for c in captions[:10])
        user_msg = (
            f"Handle: @{handle}\n"
            f"Display Name: {display_name}\n"
            f"Platform: {platform}\n"
            f"Recent Posts:\n{sample}"
        )
        try:
            res = await wiring.chain.complete(
                [
                    {"role": "system", "content": NICHE_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                tier="small",
            )
            raw = (res.completion.choices[0].message.content or "").strip()
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
                title = str(parsed.get("title") or "").strip()
                keywords = [
                    str(k).strip()
                    for k in parsed.get("keywords") or []
                    if str(k).strip()
                ]
                if title and keywords:
                    return title, keywords
        except Exception as exc:  # noqa: BLE001 - LLM inference is best effort; fallback handles it
            log.warning("LLM niche inference failed for @%s: %s", handle, exc)

    # 2. Heuristic fallback from hashtags and captions
    hashtags: list[str] = []
    for c in captions:
        hashtags.extend(re.findall(r"#([a-zA-Z0-9_]+)", c.lower()))

    stopwords = {
        "this", "that", "with", "from", "have", "what", "your", "para", "como", "sobre",
        "este", "esta", "pero", "todo", "more", "will", "when", "just", "like", "they",
        "some", "here", "there", "then", "into", "only", "also", "been", "would", "could",
    }
    words: list[str] = []
    for c in captions:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", c.lower())
        words.extend(w for w in cleaned.split() if len(w) >= 4 and w not in stopwords)

    top_hashtags = [h for h, _ in Counter(hashtags).most_common(5)]
    top_words = [w for w, _ in Counter(words).most_common(5)]

    keywords = top_hashtags or top_words or [handle.lstrip("@").lower(), platform]

    if top_hashtags:
        title = f"{top_hashtags[0].capitalize()} Content"
    elif top_words:
        first = top_words[0].capitalize()
        second = f" & {top_words[1].capitalize()}" if len(top_words) > 1 else " Content"
        title = f"{first}{second}"
    elif display_name:
        title = f"{display_name} Content"
    else:
        title = f"{handle.lstrip('@').capitalize()} Niche"

    return title, keywords[:5]


def _inherit_anchor_voice_if_available(profile_id: int) -> Any | None:
    from types import SimpleNamespace

    from django.db import transaction

    from apps.intelligence.models import GENERAL, VoiceProfile, VoiceSource
    from apps.profiles.models import SocialProfile

    prof = SocialProfile.objects.select_related("user").filter(pk=profile_id).first()
    if not prof:
        return None
    anchor = (
        VoiceProfile.objects.filter(
            profile__user_id=prof.user_id,
            is_current=True,
            source=VoiceSource.POSTS,
        )
        .exclude(profile_id=profile_id)
        .order_by("-created_at")
        .first()
    )
    if not anchor:
        return None

    with transaction.atomic():
        VoiceProfile.objects.filter(
            profile_id=profile_id, platform=GENERAL
        ).update(is_current=False)
        clone = VoiceProfile.objects.create(
            profile_id=profile_id,
            platform=GENERAL,
            version=1,
            is_current=True,
            source=VoiceSource.POSTS,
            payload=anchor.payload,
            model=anchor.model,
            prompt_version=anchor.prompt_version,
        )
    return SimpleNamespace(
        status="inherited",
        voice=clone,
        posts_found=anchor.examples.count(),
        reason=f"inherited from anchor profile {anchor.profile_id}",
    )


async def _ensure_niche_and_competitors(
    wiring: Any,
    profile_id: int,
    posts: Sequence[Any],
) -> dict[str, Any]:
    if not getattr(wiring, "competitors", None) and not getattr(wiring, "chain", None):
        return {}

    from apps.connections.models import ConnectedAccount
    from apps.intelligence.models import (
        NichePreference,
        NichePreferenceHandle,
        NichePreferenceKeyword,
        NicheSource,
    )
    from apps.profiles.models import HandleOrigin, SocialProfile
    from lumi_ai.competitors.niche import make_niche_key, slugify
    from lumi_ai.competitors.pipeline import run_peer_pipeline
    from lumi_ai.competitors.tools import _rank_authors

    profile = await aio(
        lambda: SocialProfile.objects.select_related("handle")
        .filter(pk=profile_id)
        .first()
    )()
    if not profile:
        return {}

    handle_str = profile.handle.handle_normalized or profile.handle.handle_display or ""
    platform = profile.handle.platform
    own_clean = handle_str.lstrip("@").lower()

    acc = await aio(
        lambda: ConnectedAccount.objects.filter(social_profile_id=profile_id).first()
    )()
    display_name = acc.display_name if acc else handle_str

    MIN_POSTS_FOR_INDEPENDENT_PERSONA = 5
    has_sufficient_volume = len(posts) >= MIN_POSTS_FOR_INDEPENDENT_PERSONA

    pref = await aio(
        lambda: NichePreference.objects.filter(
            profile_id=profile_id, is_active=True
        ).first()
    )()
    if pref is None:
        # If low volume on this connection (e.g. LinkedIn with only 4 posts),
        # inherit the niche from the user's primary/richer profile instead of guessing!
        primary_pref = None
        if not has_sufficient_volume:

            def _find_primary_pref() -> NichePreference | None:
                from django.db.models import Count

                ranked = (
                    SocialProfile.objects.filter(
                        user_id=profile.user_id,
                        niche_preferences__is_active=True,
                    )
                    .exclude(pk=profile_id)
                    .annotate(post_count=Count("handle__posts"))
                    .order_by("-post_count")
                    .first()
                )
                if ranked:
                    return NichePreference.objects.filter(
                        profile=ranked, is_active=True
                    ).first()
                return None

            primary_pref = await aio(_find_primary_pref)()

        if primary_pref is not None:

            def _adopt_primary_pref() -> NichePreference:
                p, _ = NichePreference.objects.update_or_create(
                    profile_id=profile_id,
                    is_active=True,
                    defaults={
                        "niche_key": primary_pref.niche_key,
                        "title": primary_pref.title,
                        "source": NicheSource.INFERRED,
                    },
                )
                for kw in primary_pref.keywords.all():
                    NichePreferenceKeyword.objects.get_or_create(
                        preference=p,
                        keyword=kw.keyword,
                    )
                return p

            pref = await aio(_adopt_primary_pref)()
        else:
            title, keywords = await _infer_niche(
                wiring,
                handle=handle_str,
                display_name=display_name,
                platform=platform,
                posts=posts,
            )
            try:
                niche_key = make_niche_key(title)
            except ValueError:
                slug = slugify(handle_str) or "creator"
                niche_key = f"{slug}:global"

            def _save_pref() -> NichePreference:
                p, _ = NichePreference.objects.update_or_create(
                    profile_id=profile_id,
                    is_active=True,
                    defaults={
                        "niche_key": niche_key,
                        "title": title[:200],
                        "source": NicheSource.INFERRED,
                    },
                )
                for kw in keywords[:5]:
                    clean_kw = kw.strip().lower()[:100]
                    if clean_kw:
                        NichePreferenceKeyword.objects.get_or_create(
                            preference=p,
                            keyword=clean_kw,
                        )
                return p

            pref = await aio(_save_pref)()

    has_handles = await aio(
        lambda: NichePreferenceHandle.objects.filter(preference=pref).exists()
    )()
    chosen_handles: list[str] = []
    if not has_handles and getattr(wiring, "competitors", None) is not None:
        if platform not in ("x", "instagram", "tiktok"):
            # Networks like LinkedIn do not support keyword search; copy peer handles from primary profile
            def _copy_primary_handles() -> list[str]:
                copied = []
                other_handles = (
                    NichePreferenceHandle.objects.filter(
                        preference__profile__user_id=profile.user_id
                    )
                    .exclude(preference=pref)
                    .select_related("handle")
                )
                for oh in other_handles:
                    NichePreferenceHandle.objects.get_or_create(
                        preference=pref,
                        handle=oh.handle,
                    )
                    copied.append(oh.handle.handle_normalized)
                return copied

            chosen_handles = await aio(_copy_primary_handles)()
        else:
            kw_list = await aio(
                lambda: list(pref.keywords.values_list("keyword", flat=True))
            )()
            search_query = kw_list[0] if kw_list else pref.title
            try:
                cfg = wiring.config
                found = await wiring.competitors.pipeline.social.search_posts(
                    platform, search_query, cfg.peer_discovery_posts
                )
                chosen_handles = _rank_authors(
                    found, exclude=own_clean, limit=cfg.peer_max_accounts
                )

                def _save_handles() -> None:
                    for ch in chosen_handles:
                        hid = services.get_or_create_handle(
                            platform, ch, origin=HandleOrigin.NICHE
                        )
                        NichePreferenceHandle.objects.get_or_create(
                            preference=pref,
                            handle_id=hid,
                        )

                await aio(_save_handles)()
            except Exception as exc:  # noqa: BLE001 - third-party social search failure must not crash bootstrap
                log.warning(
                    "Competitor discovery search failed for profile %s: %s",
                    profile_id,
                    exc,
                )
    else:
        chosen_handles = await aio(
            lambda: list(
                NichePreferenceHandle.objects.filter(preference=pref).values_list(
                    "handle__handle_normalized", flat=True
                )
            )
        )()

    report_id = None
    if (
        chosen_handles
        and getattr(wiring, "competitors", None) is not None
        and platform in ("x", "instagram", "tiktok")
    ):
        try:
            res = await run_peer_pipeline(
                wiring.competitors.pipeline,
                profile_id=profile_id,
                platform=platform,
                niche=pref.title,
                niche_key=pref.niche_key,
                handles=chosen_handles,
            )
            report_id = res.saved.id
        except Exception as exc:  # noqa: BLE001 - peer pipeline failure must not crash bootstrap
            log.warning(
                "Peer pipeline execution failed for profile %s: %s",
                profile_id,
                exc,
            )

    return {
        "niche": pref.title,
        "niche_key": pref.niche_key,
        "competitors": chosen_handles,
        "report_id": report_id,
    }


@jobs.register(REFRESH_KIND)
def refresh_profile(ctx: JobContext) -> dict[str, Any]:
    if ctx.profile_id is None:
        raise JobError("validation_error", "El trabajo no trae un perfil.")
    from apps.intelligence.wiring import get_wiring

    wiring = get_wiring()
    synced = _sync(wiring, ctx.profile_id)
    if synced is None:
        raise JobError(
            "profiles.sync_failed",
            "No se pudieron leer tus publicaciones. Revisa que la cuenta siga conectada.",
        )
    jobs.set_progress(ctx.id, PROGRESS_SYNCED)

    posts = async_to_sync(wiring.posts.list_posts)(
        ctx.profile_id, limit=wiring.config.voice_corpus_limit
    )
    indexed = wiring.indexer.index_posts(posts)
    return {
        "posts_synced": synced["stored"],
        "posts_indexed": indexed,
        "complete": synced["complete"],
        "flagged_deleted": synced["flagged_deleted"],
    }


def _sync(wiring: Any, profile_id: int) -> dict[str, Any] | None:
    """Pull the connected account's posts. ``None`` when the feed could not be read."""
    try:
        return async_to_sync(wiring.post_sync.sync_own_posts)(profile_id)
    except SocialDataError as exc:
        log.warning(
            "own post sync failed for profile %s (%s): %s",
            profile_id,
            type(exc).__name__,
            exc,
        )
        return None
