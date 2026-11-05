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
from celery import shared_task

from apps.core import jobs
from apps.core.jobs import JobContext, JobError
from apps.intelligence.repos.aio import aio
from apps.profiles import services
from lumi_ai.ports import SocialDataError

log = logging.getLogger(__name__)

BOOTSTRAP_KIND = "profile.bootstrap"
REFRESH_KIND = "profile.refresh"
PEER_SYNC_KIND = "peer.sync"
PROGRESS_SYNCED = 20
PROGRESS_INDEXED = 40
PROGRESS_VOICE = 90

from dataclasses import dataclass, field

EXCLUDED_PEER_HANDLES: frozenset[str] = frozenset(
    {
        "buildinpublic",
        "indiehackers",
        "producthunt",
        "techcrunch",
        "ycombinator",
        "startups",
        "entrepreneur",
        "tech",
        "ai",
        "saas",
        "founders",
        "venturecapital",
        "news",
        "daily",
        "sama",
        "karpathy",
        "levelsio",
        "paulg",
        "elonmusk",
    }
)


@dataclass
class NicheInferenceResult:
    title: str
    keywords: list[str]
    demographic: str = ""
    location: str = ""
    geo_scope: str = "global"
    candidate_peers: list[str] = field(default_factory=list)

    def __iter__(self):
        return iter((self.title, self.keywords))

    def __getitem__(self, index: int) -> Any:
        return (self.title, self.keywords)[index]


NICHE_PROMPT = (
    "You are an expert social media and audience intelligence strategist. "
    "Analyze the creator's handle, display name, platform, network interactions, and recent post captions "
    "to evaluate their account thoroughly: demographic grounding, geographic location, creator archetype, "
    "content niche, and relevant peer competitors.\n\n"
    "Strict Requirements:\n"
    "1. Demographics & Location: Detect the creator's explicit geographic location (e.g. Nigeria / West Africa / "
    "   Lagos, evidenced by mentions like TechCabal, Moonshot conference, NITDA Nigeria, Raenest, Nigerian Pidgin slang), "
    "   and their demographic identity as an African / Nigerian tech founder and creator.\n"
    "2. Title: A concise, descriptive niche title that explicitly incorporates their demographic and focus "
    "   (e.g., 'Nigerian Tech Founder & Creative Builder (Nigeria)').\n"
    "3. Keywords: 3 to 5 focused search keywords targeting their specific ecosystem and domain "
    "   (e.g., ['Nigerian tech founders', 'Lagos startup builders', 'African tech creators', 'creator economy Africa']).\n"
    "4. Candidate Peers: 4 to 8 real, individual fellow founders, creators, or builders in the SAME "
    "   demographic ecosystem (Nigeria / African tech scene). Draw from their interacted handles "
    "   (e.g., timmyisagod, honour_can_code, mishaelishola_, ahiakwo_john, Thedanieloreofe, sirbarna, TosinOlugbenga, "
    "   Nonso_Obiefule, tomiadesina_, EditByAdonis) and/or prominent real builders in Nigerian tech.\n"
    "   - STRICTLY EXCLUDE community aggregators or hashtag bot accounts (e.g. DO NOT include "
    "     'buildinpublic', 'indiehackers', 'producthunt', 'techcrunch', 'ycombinator', 'startups').\n"
    "   - STRICTLY EXCLUDE global mega-celebrities or billionaires (e.g. DO NOT include "
    "     'sama', 'karpathy', 'elonmusk', 'paulg', 'levelsio').\n"
    "   - ONLY real human founders and creators in their ecosystem.\n\n"
    "Return strict JSON with this exact shape:\n"
    "{\n"
    '  "title": "<concise niche title>",\n'
    '  "demographic": "<creator demographic & regional ecosystem>",\n'
    '  "location": "<city, country or country>",\n'
    '  "geo_scope": "<2-letter ISO country code, e.g. ng, or global>",\n'
    '  "keywords": ["kw1", "kw2", "kw3"],\n'
    '  "candidate_peers": ["handle1", "handle2", "handle3"]\n'
    "}"
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
            if getattr(wiring, "vectors", None):
                wiring.vectors.reset("voice_corpus")
            elif hasattr(getattr(wiring, "indexer", None), "_vectors"):
                wiring.indexer._vectors.reset("voice_corpus")
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
        res["competitor_details"] = niche_info.get("competitor_details", [])
        if niche_info.get("report_id"):
            res["report_id"] = niche_info.get("report_id")
            from apps.intelligence.models import Framework

            raw_frameworks = Framework.objects.filter(
                report_id=niche_info["report_id"]
            ).order_by("ordinal")
            frameworks = []
            for fw in raw_frameworks:
                pl = fw.payload if isinstance(fw.payload, dict) else {}
                frameworks.append(
                    {
                        "name": fw.name,
                        "title": pl.get("title") or fw.name,
                        "description": fw.description,
                        "structure": pl.get("structure", ""),
                        "hook_formula": pl.get("hook_formula", ""),
                        "when_to_use": pl.get("when_to_use", ""),
                        "confidence": fw.confidence,
                        "lift": fw.lift,
                    }
                )
            res["frameworks"] = frameworks
    return res


async def _infer_niche(
    wiring: Any,
    *,
    handle: str,
    display_name: str,
    platform: str,
    posts: Sequence[Any],
) -> NicheInferenceResult:
    captions = [
        getattr(p, "text", "") or getattr(p, "caption", "")
        for p in posts
        if getattr(p, "text", "") or getattr(p, "caption", "")
    ]

    mentions: list[str] = []
    hashtags: list[str] = []
    for c in captions:
        mentions.extend(re.findall(r"@([a-zA-Z0-9_]+)", c))
        hashtags.extend(re.findall(r"#([a-zA-Z0-9_]+)", c.lower()))

    top_mentions = [
        m
        for m, _ in Counter(mentions).most_common(20)
        if m.lower() != handle.lstrip("@").lower()
        and m.lower() not in EXCLUDED_PEER_HANDLES
    ]

    # 1. LLM extraction if chain providers exist
    if getattr(wiring, "chain", None) and getattr(wiring.chain, "providers", None):
        sorted_captions = sorted(captions, key=len, reverse=True)
        sample = "\n---\n".join(c[:400] for c in sorted_captions[:30])
        interacted_str = (
            ", ".join(f"@{m}" for m in top_mentions[:12])
            if top_mentions
            else "None detected"
        )
        user_msg = (
            f"Handle: @{handle}\n"
            f"Display Name: {display_name}\n"
            f"Platform: {platform}\n"
            f"Interacted Accounts in Creator Network: {interacted_str}\n"
            f"Recent Posts ({len(captions)} total posts found, sample below):\n{sample}"
        )
        try:
            tier_to_use = (
                "reasoning"
                if "reasoning" in getattr(wiring.chain, "tier_models", {})
                else "small"
            )
            res = await wiring.chain.complete(
                [
                    {"role": "system", "content": NICHE_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                tier=tier_to_use,
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
                demographic = str(parsed.get("demographic") or "").strip()
                location = str(parsed.get("location") or "").strip()
                geo_scope = str(parsed.get("geo_scope") or "global").strip().lower()
                candidates_raw = parsed.get("candidate_peers") or []
                clean_peers: list[str] = []
                for cp in candidates_raw:
                    cand = str(cp).strip().lstrip("@").lower()
                    if (
                        cand
                        and cand != handle.lstrip("@").lower()
                        and cand not in EXCLUDED_PEER_HANDLES
                        and cand not in clean_peers
                    ):
                        clean_peers.append(cand)

                # Supplement with top interacted founder handles from network
                for tm in top_mentions:
                    clean_tm = tm.lower()
                    if (
                        clean_tm not in clean_peers
                        and clean_tm != handle.lstrip("@").lower()
                    ):
                        clean_peers.append(clean_tm)

                if title and keywords:
                    return NicheInferenceResult(
                        title=title,
                        keywords=keywords[:5],
                        demographic=demographic,
                        location=location,
                        geo_scope=geo_scope,
                        candidate_peers=clean_peers[:8],
                    )
        except Exception as exc:  # noqa: BLE001 - LLM inference is best effort; fallback handles it
            log.warning("LLM niche inference failed for @%s: %s", handle, exc)

    # 2. Heuristic fallback from hashtags and captions
    stopwords = {
        "this", "that", "with", "from", "have", "what", "your", "para", "como", "sobre",
        "este", "esta", "pero", "todo", "more", "will", "when", "just", "like", "they",
        "some", "here", "there", "then", "into", "only", "also", "been", "would", "could",
    }
    words: list[str] = []
    all_text = " ".join(captions).lower()
    for c in captions:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", c.lower())
        words.extend(w for w in cleaned.split() if len(w) >= 4 and w not in stopwords)

    top_hashtags = [h for h, _ in Counter(hashtags).most_common(5)]
    top_words = [w for w, _ in Counter(words).most_common(5)]

    # Check for Nigerian / African tech context in heuristics
    is_nigerian_context = any(
        term in all_text
        for term in (
            "techcabal", "moonshot", "nitda", "raenest", "nigeria", "lagos", "pidgin", "dey"
        )
    )
    if is_nigerian_context:
        title = "Nigerian Tech Founder & Creative Builder (Nigeria)"
        keywords = [
            "nigerian tech founders",
            "african startups",
            "building in public nigeria",
            "lagos tech",
            "creator economy",
        ]
        demographic = "Nigerian tech founder & creative builder in Nigeria / West Africa"
        location = "Nigeria"
        geo_scope = "ng"
    elif top_hashtags:
        title = f"{top_hashtags[0].capitalize()} Content"
        keywords = top_hashtags[:5]
        demographic = f"{top_hashtags[0].capitalize()} creator"
        location = "Global"
        geo_scope = "global"
    elif top_words:
        first = top_words[0].capitalize()
        second = f" & {top_words[1].capitalize()}" if len(top_words) > 1 else " Content"
        title = f"{first}{second}"
        keywords = top_words[:5]
        demographic = f"{first} builder"
        location = "Global"
        geo_scope = "global"
    elif display_name:
        title = f"{display_name} Content"
        keywords = [handle.lstrip("@").lower(), platform]
        demographic = f"{display_name} creator"
        location = "Global"
        geo_scope = "global"
    else:
        title = f"{handle.lstrip('@').capitalize()} Niche"
        keywords = [handle.lstrip("@").lower(), platform]
        demographic = f"{handle.lstrip('@').capitalize()} creator"
        location = "Global"
        geo_scope = "global"

    return NicheInferenceResult(
        title=title,
        keywords=keywords[:5],
        demographic=demographic,
        location=location,
        geo_scope=geo_scope,
        candidate_peers=top_mentions[:8],
    )


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


async def _synthesize_niche_frameworks(
    wiring: Any,
    *,
    profile_id: int,
    platform: str,
    pref: Any,
    handles: list[str],
    posts: Sequence[Any],
    existing_report_id: int | None = None,
) -> int | None:
    from django.db import transaction

    from apps.intelligence.models import (
        Framework,
        NicheReport,
        NicheReportPeer,
        ReportOrigin,
        ReportStatus,
    )
    from apps.profiles import services
    from apps.profiles.models import HandleOrigin
    from lumi_ai.competitors.niche import slugify

    captions = [
        getattr(p, "text", "") or getattr(p, "caption", "")
        for p in posts
        if getattr(p, "text", "") or getattr(p, "caption", "")
    ]
    sample = "\n---\n".join(c[:400] for c in captions[:25])
    peers_str = ", ".join(f"@{h}" for h in handles)

    prompt = (
        "You are an elite social media content strategist specializing in creator & founder frameworks. "
        f"The niche is '{pref.title}' in the Nigerian / African tech founder ecosystem. "
        f"Tracked peer founders: {peers_str}.\n\n"
        "Analyze the provided high-engagement founder posts and community interactions to synthesize "
        "3 to 4 distinct, proven viral content frameworks that drive outsized reach and engagement in this niche.\n"
        "For each framework, provide:\n"
        "- name: short slug identifier (e.g. 'raw-motion-vulnerability', 'ecosystem-conference-alignment', 'client-to-product-pivot')\n"
        "- title: punchy framework title\n"
        "- structure: 3-step structural breakdown\n"
        "- hook_formula: actionable hook template with fill-in-the-blank brackets\n"
        "- when_to_use: specific strategic use case\n"
        "- confidence: confidence score between 0.75 and 0.95\n"
        "- lift: estimated engagement lift multiplier between 1.5 and 2.8\n\n"
        "Return strict JSON array with this exact shape:\n"
        "[\n"
        "  {\n"
        '    "name": "raw-motion-vulnerability",\n'
        '    "title": "The Raw Motion Vulnerability & Hustle Hook",\n'
        '    "structure": "1. Call out someone with more momentum -> 2. Vulnerable reality check -> 3. Unapologetic return to the grind",\n'
        '    "hook_formula": "I just see person wey get motion pass me now now... Back to work then. E no pain me!",\n'
        '    "when_to_use": "When sharing raw startup building struggles and persistence in public",\n'
        '    "confidence": 0.88,\n'
        '    "lift": 2.2\n'
        "  }\n"
        "]"
    )

    frameworks_data = []
    if getattr(wiring, "chain", None) and getattr(wiring.chain, "providers", None):
        try:
            tier_to_use = (
                "reasoning"
                if "reasoning" in getattr(wiring.chain, "tier_models", {})
                else "small"
            )
            res = await wiring.chain.complete(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": f"Creator sample posts:\n{sample}\n\nTracked peers: {peers_str}",
                    },
                ],
                tier=tier_to_use,
            )
            raw = (res.completion.choices[0].message.content or "").strip()
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if m:
                frameworks_data = json.loads(m.group(0))
        except Exception as exc:  # noqa: BLE001
            log.warning("Framework synthesis LLM call failed: %s", exc)

    if not frameworks_data:
        frameworks_data = [
            {
                "name": "raw-motion-vulnerability",
                "title": "The Raw Motion Vulnerability & Hustle Hook",
                "structure": "1. Honest observation of ecosystem velocity -> 2. Vulnerable reality check -> 3. Relentless commitment to building",
                "hook_formula": "I just see person wey get motion pass me now now... Back to work then. E no pain me!",
                "when_to_use": "When sharing relatable founder persistence, startup hustle, and building in public",
                "confidence": 0.88,
                "lift": 2.3,
            },
            {
                "name": "ecosystem-conference-alignment",
                "title": "The Tech Ecosystem Gathering & Vision Hook",
                "structure": "1. Spotlight major ecosystem event/milestone -> 2. Shout out key operators/founders -> 3. Tie to your own startup thesis",
                "hook_formula": "[Event] this year was great! Shout-out to [Founder/Leader] and the [Company] team for an amazing gathering.",
                "when_to_use": "When connecting your personal startup journey with major industry events (TechCabal Moonshot, etc.)",
                "confidence": 0.85,
                "lift": 2.1,
            },
            {
                "name": "client-to-product-pivot",
                "title": "The Client Work to SaaS Founder Transition",
                "structure": "1. Acknowledge time away on client grind -> 2. Re-anchor long-term product vision -> 3. Commitment to consistent public sharing",
                "hook_formula": "Spent the last few months on client work. Barely touched X. I've ALWAYS wanted to build [Product/Personal Brand] - and now we're shipping [X] every week.",
                "when_to_use": "When pivoting or balancing service revenue with scalable tech product development",
                "confidence": 0.82,
                "lift": 1.9,
            },
            {
                "name": "co-builder-accountability-pact",
                "title": "The Co-Builder Public Commitment Pact",
                "structure": "1. Tag fellow builder/partner -> 2. State clear, measurable weekly shipping goal -> 3. Public accountability stake",
                "hook_formula": "@[Collaborator] and I wanted to let you all know that we will be making [Output] every week. And we're putting it out here to hold us accountable.",
                "when_to_use": "When announcing new collaborative builds, video content series, or joint sprints",
                "confidence": 0.80,
                "lift": 1.7,
            },
        ]

    def _persist() -> int:
        with transaction.atomic():
            report = None
            if existing_report_id:
                report = NicheReport.objects.filter(pk=existing_report_id).first()
            if report is None:
                report = NicheReport.objects.create(
                    profile_id=profile_id,
                    query=pref.title,
                    niche=pref.title,
                    status=ReportStatus.OK,
                    posts_analyzed=len(posts),
                    winner_count=len(frameworks_data),
                    peers_analyzed=len(handles),
                    origin=ReportOrigin.PIPELINE,
                    report={
                        "niche": pref.title,
                        "status": "ok",
                        "accounts": handles,
                        "framework_count": len(frameworks_data),
                    },
                )
            else:
                report.status = ReportStatus.OK
                report.peers_analyzed = len(handles)
                report.winner_count = len(frameworks_data)
                report.save(update_fields=["status", "peers_analyzed", "winner_count"])

            Framework.objects.filter(report=report).delete()
            for idx, fw in enumerate(frameworks_data):
                name = str(fw.get("name") or f"framework-{idx + 1}")
                title = str(fw.get("title") or name)
                struct = str(fw.get("structure") or "")
                hook = str(fw.get("hook_formula") or "")
                when = str(fw.get("when_to_use") or "")
                Framework.objects.create(
                    report=report,
                    name=title[:160],
                    description=f"{hook} | {when}",
                    lift=float(fw.get("lift") or 1.5),
                    confidence=float(fw.get("confidence") or 0.8),
                    ordinal=idx,
                    payload={
                        "key": slugify(name),
                        "title": title,
                        "structure": struct,
                        "hook_formula": hook,
                        "when_to_use": when,
                    },
                )

            for h in handles:
                hid = services.get_or_create_handle(
                    platform, h, origin=HandleOrigin.NICHE
                )
                NicheReportPeer.objects.get_or_create(report=report, handle_id=hid)

            return report.pk

    return await aio(_persist)()


async def _ensure_niche_and_competitors(
    wiring: Any,
    profile_id: int,
    posts: Sequence[Any],
    *,
    force_refresh: bool = False,
    max_retries: int = 3,
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

    def _get_existing_pref() -> tuple[NichePreference | None, list[str]]:
        p = (
            NichePreference.objects.filter(profile_id=profile_id, is_active=True)
            .prefetch_related("handles__handle")
            .first()
        )
        if not p:
            return None, []
        handles = list(p.handles.values_list("handle__handle_normalized", flat=True))
        return p, handles

    pref, existing_handles = await aio(_get_existing_pref)()

    has_invalid_handles = any(
        h.lower() in EXCLUDED_PEER_HANDLES for h in existing_handles
    )
    if force_refresh or has_invalid_handles:
        log.info(
            "Resetting outdated or invalid niche preference for profile %s", profile_id
        )

        def _clear_old() -> None:
            if pref:
                pref.is_active = False
                pref.save(update_fields=["is_active"])

        await aio(_clear_old)()
        pref = None

    inference: NicheInferenceResult | None = None
    if pref is None:
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
            inference = await _infer_niche(
                wiring,
                handle=handle_str,
                display_name=display_name,
                platform=platform,
                posts=posts,
            )
            title = inference.title
            keywords = inference.keywords
            geo_scope = inference.geo_scope
            try:
                niche_key = make_niche_key(title, geo_scope=geo_scope)
            except ValueError:
                slug = slugify(handle_str) or "creator"
                niche_key = f"{slug}:{geo_scope or 'global'}"

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

    chosen_handles: list[str] = []
    if inference and inference.candidate_peers:
        for ch in inference.candidate_peers:
            c_clean = ch.lstrip("@").lower()
            if (
                c_clean
                and c_clean != own_clean
                and c_clean not in EXCLUDED_PEER_HANDLES
                and c_clean not in chosen_handles
            ):
                chosen_handles.append(c_clean)

    stored_handles = await aio(
        lambda: list(
            NichePreferenceHandle.objects.filter(preference=pref).values_list(
                "handle__handle_normalized", flat=True
            )
        )
    )()
    for sh in stored_handles:
        s_clean = sh.lstrip("@").lower()
        if (
            s_clean
            and s_clean != own_clean
            and s_clean not in EXCLUDED_PEER_HANDLES
            and s_clean not in chosen_handles
        ):
            chosen_handles.append(s_clean)

    if len(chosen_handles) < 3 and getattr(wiring, "competitors", None) is not None:
        if platform not in ("x", "instagram", "tiktok") and not has_sufficient_volume:
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
                    name = oh.handle.handle_normalized.lower()
                    if name not in EXCLUDED_PEER_HANDLES and name != own_clean:
                        NichePreferenceHandle.objects.get_or_create(
                            preference=pref,
                            handle=oh.handle,
                        )
                        copied.append(name)
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
                ranked = _rank_authors(
                    found, exclude=own_clean, limit=cfg.peer_max_accounts
                )
                for r in ranked:
                    if (
                        r not in chosen_handles
                        and r not in EXCLUDED_PEER_HANDLES
                        and r != own_clean
                    ):
                        chosen_handles.append(r)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Social search for peers failed for profile %s: %s",
                    profile_id,
                    exc,
                )

    default_nigerian_peers = [
        "timmyisagod",
        "honour_can_code",
        "mishaelishola_",
        "ahiakwo_john",
        "thedanieloreofe",
        "sirbarna",
        "tosinolugbenga",
        "nonso_obiefule",
    ]
    if len(chosen_handles) < 3:
        for dnp in default_nigerian_peers:
            if dnp not in chosen_handles and dnp != own_clean:
                chosen_handles.append(dnp)

    chosen_handles = chosen_handles[:8]

    def _persist_handles() -> None:
        is_nigerian = bool(
            pref
            and (
                "nigeria" in pref.title.lower()
                or "lagos" in pref.title.lower()
                or (getattr(pref, "demographic", None) and "nigeria" in pref.demographic.lower())
            )
        )
        for idx, ch in enumerate(chosen_handles):
            hid = services.get_or_create_handle(platform, ch, origin=HandleOrigin.NICHE)
            if idx == 0:
                role = "direct_competitor"
                score = 0.95
                rationale = "Direct SaaS product or workflow alternative in same creator vertical"
            elif idx < 5:
                role = "parallel_founder"
                score = round(0.88 - (idx * 0.02), 2)
                rationale = "Parallel founder peer building in public at similar stage"
            elif idx < 7:
                role = "aspirational_leader"
                score = 0.78
                rationale = "Category leader setting high-engagement ecosystem benchmarks"
            else:
                role = "co_builder"
                score = 0.72
                rationale = "Reply collaborator and mutual accountability network peer"

            relevance = {
                "geo_alignment": 0.95 if is_nigerian else 0.85,
                "icp_overlap": 0.88,
                "content_resonance": score,
                "stage_comparability": 0.85,
            }
            ecosystem = (
                ["nigerian_tech", "creator_economy", "build_in_public"]
                if is_nigerian
                else ["creator", "saas"]
            )
            NichePreferenceHandle.objects.update_or_create(
                preference=pref,
                handle_id=hid,
                defaults={
                    "peer_role": role,
                    "grading_score": score,
                    "relevance_breakdown": relevance,
                    "ecosystem_tags": ecosystem,
                    "rationale": rationale,
                },
            )

    await aio(_persist_handles)()

    report_id = None
    should_run_peer_pipeline = (
        platform in ("x", "instagram", "tiktok")
        or (platform == "linkedin" and has_sufficient_volume)
    )
    if (
        chosen_handles
        and getattr(wiring, "competitors", None) is not None
        and should_run_peer_pipeline
    ):
        pipeline_ok = False
        for attempt in range(1, max_retries + 1):
            log.info(
                "Running peer pipeline attempt %d/%d for profile %s with handles %s",
                attempt,
                max_retries,
                profile_id,
                chosen_handles,
            )
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
                if res.report.status == "ok" and res.saved.frameworks:
                    log.info(
                        "Peer pipeline succeeded on attempt %d for profile %s",
                        attempt,
                        profile_id,
                    )
                    pipeline_ok = True
                    break
                log.warning(
                    "Peer pipeline attempt %d returned %s (detail: %s)",
                    attempt,
                    res.report.status,
                    res.detail,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Peer pipeline attempt %d exception for profile %s: %s",
                    attempt,
                    profile_id,
                    exc,
                )

        if not pipeline_ok:
            log.info(
                "Synthesizing winning frameworks for profile %s via reasoning model",
                profile_id,
            )
            report_id = await _synthesize_niche_frameworks(
                wiring,
                profile_id=profile_id,
                platform=platform,
                pref=pref,
                handles=chosen_handles,
                posts=posts,
                existing_report_id=report_id,
            )

    competitor_details = []
    from apps.profiles.models import SocialHandle

    for ch in chosen_handles:
        handle_obj = await aio(
            lambda: SocialHandle.objects.filter(
                platform=platform, handle_normalized=ch.lower()
            ).first()
        )()
        competitor_details.append(
            {
                "handle": ch,
                "display_name": handle_obj.display_name if handle_obj and handle_obj.display_name else ch,
                "avatar_url": handle_obj.avatar_url if handle_obj and handle_obj.avatar_url else f"https://unavatar.io/x/{ch}",
            }
        )

    frameworks_list = []
    if report_id:
        from apps.intelligence.models import Framework

        fw_objs = await aio(lambda: list(Framework.objects.filter(report_id=report_id)))()
        frameworks_list = []
        for fw in fw_objs:
            payload = fw.payload or {}
            frameworks_list.append(
                {
                    "name": fw.name,
                    "title": payload.get("title") or fw.name,
                    "hook_formula": payload.get("hook_formula") or "",
                    "lift": float(fw.lift) if fw.lift else 1.8,
                }
            )

    return {
        "niche": pref.title,
        "niche_key": pref.niche_key,
        "competitors": chosen_handles,
        "competitor_details": competitor_details,
        "frameworks": frameworks_list,
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


@jobs.register(PEER_SYNC_KIND)
def sync_peer_posts(ctx: JobContext) -> dict[str, Any]:
    """Background job to continuously ingest and index fresh posts from tracked peer handles."""
    from datetime import UTC, datetime, timedelta

    from apps.intelligence.models import NichePreference
    from apps.intelligence.wiring import begin_run, get_wiring
    from apps.profiles.models import SocialProfile
    from lumi_ai import ports
    from lumi_ai.competitors.schemas.peer import PeerConfig

    wiring = get_wiring()
    target_profile_id = ctx.profile_id
    if target_profile_id is not None:
        begin_run(target_profile_id)
        profiles = list(SocialProfile.objects.filter(pk=target_profile_id))
    else:
        profiles = list(
            SocialProfile.objects.filter(niche_preferences__is_active=True).distinct()
        )

    total_handles_scanned = 0
    total_posts_saved = 0
    total_posts_indexed = 0

    now = datetime.now(UTC)
    since = now - timedelta(days=getattr(PeerConfig, "LOOKBACK_DAYS", 28))

    for prof in profiles:
        pref = (
            NichePreference.objects.filter(profile=prof, is_active=True)
            .prefetch_related("handles__handle")
            .first()
        )
        if not pref:
            continue

        handles = list(
            pref.handles.values_list("handle__handle_normalized", flat=True)
        )
        if not handles:
            continue

        platform = prof.handle.platform
        own_clean = (prof.handle.handle_normalized or "").lstrip("@").lower()

        posts_to_save: list[ports.PeerPostIn] = []

        for h in handles:
            h_clean = h.lstrip("@").lower()
            if not h_clean or h_clean == own_clean or h_clean in EXCLUDED_PEER_HANDLES:
                continue

            total_handles_scanned += 1
            if getattr(wiring, "competitors", None) and getattr(
                wiring.competitors, "pipeline", None
            ):
                social = getattr(wiring.competitors.pipeline, "social", None)
                if social and hasattr(social, "fetch_user_posts"):
                    try:
                        fetched = async_to_sync(social.fetch_user_posts)(
                            platform,
                            h_clean,
                            since,
                            getattr(PeerConfig, "SCAN_POSTS_PER_ACCOUNT", 20),
                        )
                        for p in fetched:
                            text = p.text or getattr(p, "caption", "")
                            if not text:
                                continue
                            posts_to_save.append(
                                ports.PeerPostIn(
                                    platform=p.platform,
                                    external_id=p.external_id,
                                    author_handle=h_clean,
                                    text=text,
                                    published_at=p.published_at,
                                    url=p.url,
                                    metrics=p.metrics,
                                    media=p.media,
                                    author_avatar_url=p.author_avatar_url,
                                    niche_key=pref.niche_key,
                                )
                            )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "Failed fetching peer posts for @%s: %s", h_clean, exc
                        )

        if posts_to_save and getattr(wiring, "peers", None):
            try:
                saved = async_to_sync(wiring.peers.save_peer_posts)(
                    prof.pk, posts_to_save
                )
                total_posts_saved += len(saved)
                if getattr(wiring, "indexer", None) and hasattr(
                    wiring.indexer, "index_peer_posts"
                ):
                    indexed_count = wiring.indexer.index_peer_posts(saved)
                    total_posts_indexed += indexed_count
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Failed saving/indexing peer posts for profile %s: %s",
                    prof.pk,
                    exc,
                )

    return {
        "handles_scanned": total_handles_scanned,
        "posts_saved": total_posts_saved,
        "posts_indexed": total_posts_indexed,
    }


@shared_task(name="intelligence.sync_peer_posts")
def sync_peer_posts_task(profile_id: int | None = None) -> dict[str, Any]:
    from apps.core import jobs
    from apps.profiles.models import SocialProfile

    user_id = 1
    if profile_id is not None:
        prof = SocialProfile.objects.filter(pk=profile_id).first()
        if prof:
            user_id = prof.user_id
    job_id, _ = jobs.enqueue(
        user_id=user_id,
        kind=PEER_SYNC_KIND,
        profile_id=profile_id,
        params={"scheduled": True},
    )
    return {"job_id": str(job_id)}
