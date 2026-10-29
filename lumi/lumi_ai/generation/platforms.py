"""What each network accepts and how its posts are usually written.

``hard_limit`` is the number the network rejects above, with where it comes from. Everything
else (target length, tone, hashtags) is writing advice for the model and is not a promise about
what the network enforces, except the one cap marked ``hashtag_cap_enforced``. Facebook is the
honest outlier: Meta publishes no limit, so its number is the widely observed one and the
source field says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

from lumi_ai.ports import Platform

PLATFORMS: tuple[str, ...] = get_args(Platform)


class UnknownPlatform(ValueError):
    """The platform is not one of x, linkedin, facebook, tiktok, instagram."""


@dataclass(frozen=True, slots=True)
class PlatformRules:
    platform: Platform
    label: str
    hard_limit: int
    limit_source: str
    limit_is_official: bool
    target_min: int  # recommended characters, advice only
    target_max: int
    hashtags_min: int
    hashtags_max: int
    hashtag_cap_enforced: bool
    utf16_length: bool  # the network counts UTF-16 code units (emoji count twice)
    guidance: str


_X = PlatformRules(
    platform="x",
    label="X",
    hard_limit=280,
    limit_source=(
        "X Help Center, 'How to post on X': 280 characters for a standard account. "
        "X Premium accounts may post up to 25,000, but the account tier is unknown here, "
        "so the standard limit is used. X counts every link as 23 characters; this check counts "
        "the real text, which can only be stricter."
    ),
    limit_is_official=True,
    target_min=0,
    target_max=280,
    hashtags_min=0,
    hashtags_max=1,
    hashtag_cap_enforced=False,
    utf16_length=False,
    guidance=(
        "- Under 280 characters in total. Punchy, one idea, no filler.\n"
        "- Short lines, a blank line between thoughts, a hook in the first line.\n"
        "- 0 or 1 hashtag; never a hashtag pile.\n"
        "- Close with a question or a sharp statement that invites a reply."
    ),
)

_LINKEDIN = PlatformRules(
    platform="linkedin",
    label="LinkedIn",
    hard_limit=3000,
    limit_source=(
        "LinkedIn Help, 'Post and share updates' (linkedin.com/help/linkedin/answer/a528176): "
        "posts can contain up to 3,000 characters."
    ),
    limit_is_official=True,
    target_min=600,
    target_max=1800,
    hashtags_min=0,
    hashtags_max=5,
    hashtag_cap_enforced=False,
    utf16_length=False,
    guidance=(
        "- Up to 3,000 characters; 600 to 1,800 reads best. Never pad: expand only with what the "
        "source or the brief supports, and never invent facts, numbers or stories.\n"
        "- The first two lines must make people open 'see more'; they are all that shows before the fold.\n"
        "- Short paragraphs of one to three lines with blank lines between them; a list only for real takeaways.\n"
        "- Professional but first person and concrete: what happened, what was learned.\n"
        "- 0 to 5 hashtags, together at the very end. Links are fine in the body.\n"
        "- End with a genuine question for peers."
    ),
)

_FACEBOOK = PlatformRules(
    platform="facebook",
    label="Facebook",
    hard_limit=63_206,
    limit_source=(
        "Not published by Meta. 63,206 characters is the long-observed ceiling of a Facebook "
        "post (first reported by TechCrunch when Facebook raised the old 5,000 limit); treat it "
        "as unofficial. What matters in practice is the 'See more' fold at roughly 477 characters "
        "in the feed, also observed rather than documented."
    ),
    limit_is_official=False,
    target_min=80,
    target_max=600,
    hashtags_min=0,
    hashtags_max=3,
    hashtag_cap_enforced=False,
    utf16_length=False,
    guidance=(
        "- No real length limit, but the feed cuts around 477 characters: put the point and the hook "
        "before that. 80 to 600 characters works best; go longer only for a real story.\n"
        "- Conversational and personal, as if talking to friends and followers; plain words, no jargon.\n"
        "- A link may sit in the body, but the post must make sense without it.\n"
        "- 0 to 3 hashtags; they matter little here.\n"
        "- A question or an invitation to share an experience tends to draw comments."
    ),
)

_INSTAGRAM = PlatformRules(
    platform="instagram",
    label="Instagram",
    hard_limit=2200,
    limit_source=(
        "Meta for Developers, IG User Media reference: caption maximum 2,200 characters. "
        "Hashtags: Instagram Help Center, 'Use hashtags on Instagram' (help.instagram.com/351460621611097): "
        "up to 5 per post since the December 2025 change; the API reference still says 30, so 5 is used."
    ),
    limit_is_official=True,
    target_min=150,
    target_max=1000,
    hashtags_min=0,
    hashtags_max=5,
    hashtag_cap_enforced=True,
    utf16_length=False,
    guidance=(
        "- Up to 2,200 characters including hashtags; the feed shows only the first lines, so the "
        "first line must work alone.\n"
        "- A clean opening line, then short paragraphs; storytelling that goes with an image or video.\n"
        "- At most 5 hashtags, at the end; more makes the post fail on Instagram.\n"
        "- Invite saves, shares or comments."
    ),
)

_TIKTOK = PlatformRules(
    platform="tiktok",
    label="TikTok",
    hard_limit=2200,
    limit_source=(
        "TikTok for Developers, Content Posting API 'Direct Post': video caption maximum 2,200 "
        "UTF-16 runes. TikTok's Help Center publishes no in-app limit."
    ),
    limit_is_official=True,
    target_min=40,
    target_max=300,
    hashtags_min=0,
    hashtags_max=5,
    hashtag_cap_enforced=False,
    utf16_length=True,
    guidance=(
        "- The caption is secondary to the video: short and direct, 40 to 300 characters; the hard "
        "limit is 2,200 UTF-16 units, so an emoji counts as two.\n"
        "- Open with a curiosity hook that does not repeat what the video shows.\n"
        "- Casual and energetic.\n"
        "- 3 to 5 niche hashtags are common; never fill the caption with them.\n"
        "- Close with a prompt to comment or follow."
    ),
)

RULES: dict[str, PlatformRules] = {
    r.platform: r for r in (_X, _LINKEDIN, _FACEBOOK, _INSTAGRAM, _TIKTOK)
}


def rules_for(platform: str) -> PlatformRules:
    """Rules of ``platform``. An unknown name is an error, never a silent default to X."""
    try:
        return RULES[platform.lower().strip()]
    except KeyError:
        raise UnknownPlatform(
            f"unknown platform {platform!r}; use one of: {', '.join(PLATFORMS)}"
        ) from None


def measure(platform: str, text: str) -> int:
    """Length of ``text`` the way ``platform`` counts it."""
    if rules_for(platform).utf16_length:
        return len(text.encode("utf-16-le")) // 2
    return len(text)
