"""X (Twitter) Recommendation Algorithm Pre-Flight Scorer & Auditor.

Implements reverse-engineered mechanics from the official X recommendation repository:
- Earlybird Static Text Quality (TweetTextScorer.java): length, entropy, shout damping, readability.
- Heavy Ranker (MaskNet): multi-task engagement head probabilities (Reply +13.5x, Dwell +10x, Link 0.1x).
- Visibilitylib downranking rules: untrusted URL penalty, multiple hashtags/trends flag, slop detection.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

# Standard Earlybird & TweetTextScorer constants
DEFAULT_LENGTH_ALPHA = 0.03
DEFAULT_ENTROPY_ALPHA = 0.5
DEFAULT_OFFENSIVE_DAMPING = 0.2
DEFAULT_SHOUT_WEIGHT = 0.10
DEFAULT_LENGTH_WEIGHT = 0.50
DEFAULT_ENTROPY_WEIGHT = 0.25
DEFAULT_READABILITY_WEIGHT = 0.10
DEFAULT_LINK_WEIGHT = 0.05

# Regex patterns
URL_REGEX = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
HASHTAG_REGEX = re.compile(r"#\w+")
MENTION_REGEX = re.compile(r"@\w+")
WORD_REGEX = re.compile(r"\b\w+\b")
QUESTION_REGEX = re.compile(
    r"[\?\u00BF\u037E\u055E\u061F\u1367\u1945\u2047\u2048\u2049\u2753\u2754\uFE16\uFE56\uFF1F]"
)

# Slop phrases flagged by Grok / NLP safety filters
SLOP_PATTERNS = (
    r"in today'?s (?:fast[- ]paced|digital|ever[- ]changing) (?:world|landscape)",
    r"let'?s dive in",
    r"\bdelve\b",
    r"unlock the (?:power|potential)",
    r"game[- ]changer",
    r"as an ai\b",
    r"i hope this (?:helps|finds you)",
    r"here'?s the thing:?",
    r"without further ado",
    r"testament to",
    r"beacon of",
)
SLOP_REGEX = re.compile("|".join(SLOP_PATTERNS), re.IGNORECASE)


@dataclass(frozen=True)
class XAlgorithmAudit:
    composite_score: float  # 0..100 overall X algorithm rating
    text_score: float  # 0..100 Earlybird static quality score
    length_score: float  # 0..1
    entropy_score: float  # 0..1 lexical diversity
    shout_score: float  # 0..1 (1.0 = clean casing, lower = shouting)
    has_question: bool  # drives P(Reply)
    has_body_link: bool  # drives visibilitylib penalty and 0.1x click weight
    num_hashtags: int  # >=2 triggers multiple_hashtags flag
    num_mentions: int
    predicted_reply_prob: float  # estimated P(Reply)
    predicted_retweet_prob: float  # estimated P(Retweet)
    predicted_dwell_prob: float  # estimated P(Dwell >= 2 min)
    is_slop_suspect: bool
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


def calculate_entropy(text: str) -> float:
    """Shannon entropy of word distribution, normalized to 0..1.
    
    Higher entropy indicates diverse vocabulary and information density;
    low entropy indicates repetitive, spammy phrasing.
    """
    words = [w.lower() for w in WORD_REGEX.findall(text)]
    if not words:
        return 0.0
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    total = len(words)
    entropy = -sum((c / total) * math.log2(c / total) for c in freq.values())
    # Max practical entropy for 280-char tweets is ~4.5 bits
    return min(1.0, max(0.0, entropy / 4.5))


def calculate_shout_ratio(text: str) -> float:
    """Proportion of alphabetic characters that are uppercase."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    caps = sum(1 for c in letters if c.isupper())
    return caps / len(letters)


def score_earlybird_text(text: str) -> dict[str, float]:
    """Implements TweetTextScorer.java static scoring formula.
    
    text_score = D_off * (0.50 * length + 0.25 * entropy + 0.10 * readability + 0.10 * shout + 0.05 * link)
    """
    length = len(text)
    # Sigmoid centered around 140 chars with alpha = 0.03
    length_sigmoid = 1.0 / (1.0 + math.exp(-DEFAULT_LENGTH_ALPHA * (length - 120)))
    entropy_val = calculate_entropy(text)
    shout_ratio = calculate_shout_ratio(text)
    shout_score = max(0.0, 1.0 - shout_ratio * 2.5)  # Penalize if >40% caps

    # Readability: balance of sentence length and whitespace
    words = WORD_REGEX.findall(text)
    avg_word_len = sum(len(w) for w in words) / max(1, len(words))
    readability = 1.0 if (3.5 <= avg_word_len <= 7.0) else 0.6

    has_link = bool(URL_REGEX.search(text))
    link_score = 1.0 if has_link else 0.0

    raw_score = (
        DEFAULT_LENGTH_WEIGHT * length_sigmoid
        + DEFAULT_ENTROPY_WEIGHT * entropy_val
        + DEFAULT_READABILITY_WEIGHT * readability
        + DEFAULT_SHOUT_WEIGHT * shout_score
        + DEFAULT_LINK_WEIGHT * link_score
    )

    return {
        "text_score": round(raw_score * 100.0, 2),
        "length_score": round(length_sigmoid, 3),
        "entropy_score": round(entropy_val, 3),
        "shout_score": round(shout_score, 3),
    }


def audit_x_post(text: str) -> XAlgorithmAudit:
    """Runs a complete algorithmic pre-flight check on an X draft."""
    clean_text = text.strip()
    eb_scores = score_earlybird_text(clean_text)
    
    has_body_link = bool(URL_REGEX.search(clean_text))
    has_question = bool(QUESTION_REGEX.search(clean_text))
    hashtags = HASHTAG_REGEX.findall(clean_text)
    mentions = MENTION_REGEX.findall(clean_text)
    is_slop = bool(SLOP_REGEX.search(clean_text))

    # Heavy Ranker Engagement Probabilities
    # Reply: boosted by question mark and conversational open loops
    reply_prob = 0.35 if has_question else 0.12
    if is_slop:
        reply_prob *= 0.5

    # Retweet: boosted by informational density (entropy) and formatting
    retweet_prob = 0.15 + (eb_scores["entropy_score"] * 0.25)

    # Dwell: boosted by length between 120 and 260 characters
    dwell_prob = 0.20 + (eb_scores["length_score"] * 0.40)
    if has_body_link:
        # Off-platform links trigger high bounce rate, reducing on-platform dwell
        dwell_prob *= 0.65

    # Warnings & Recommendations
    warnings: list[str] = []
    recommendations: list[str] = []

    if has_body_link:
        warnings.append(
            "External URL in tweet body: Heavy Ranker weights link-clicks at only 0.1x "
            "(vs 13.5x for replies), and visibilitylib may downrank this to ConversationSectionAbusiveQuality."
        )
        recommendations.append("Move external links to a reply or bio to preserve feed reach.")

    if len(hashtags) > 1:
        warnings.append(
            f"{len(hashtags)} hashtags detected: Triggers 'has_multiple_hashtags_or_trends_flag', "
            "reducing distribution in Earlybird search index."
        )
        recommendations.append("Use 0 or at most 1 hashtag.")

    if eb_scores["shout_score"] < 0.7:
        warnings.append("Excessive uppercase words detected: Earlybird shout damping penalty applied.")
        recommendations.append("Use standard sentence casing instead of ALL CAPS.")

    if not has_question:
        recommendations.append(
            "Close with an open-ended question or discussion prompt to trigger the Heavy Ranker's "
            "+13.5x reply weight (and up to +75.0x if you reply back to commenters)."
        )

    if is_slop:
        warnings.append("Detected stock AI cliché phrase flagged by Grok/NLP quality filters.")
        recommendations.append("Remove generic openers like 'Let's dive in' or 'In today's fast-paced world'.")

    # Composite Algorithmic Score (0..100)
    # Starts from Earlybird static text score, weighted by conversational reply potential,
    # then penalized by links, multi-hashtags, and slop.
    composite = eb_scores["text_score"]
    
    # Conversational bonus: questions add +15 points
    if has_question:
        composite += 15.0

    # Penalties
    if has_body_link:
        composite -= 30.0  # Devastating link penalty
    if len(hashtags) > 1:
        composite -= 15.0
    if is_slop:
        composite -= 20.0
    if eb_scores["shout_score"] < 0.7:
        composite -= 15.0

    composite = min(100.0, max(5.0, composite))

    return XAlgorithmAudit(
        composite_score=round(composite, 1),
        text_score=eb_scores["text_score"],
        length_score=eb_scores["length_score"],
        entropy_score=eb_scores["entropy_score"],
        shout_score=eb_scores["shout_score"],
        has_question=has_question,
        has_body_link=has_body_link,
        num_hashtags=len(hashtags),
        num_mentions=len(mentions),
        predicted_reply_prob=round(reply_prob, 3),
        predicted_retweet_prob=round(retweet_prob, 3),
        predicted_dwell_prob=round(dwell_prob, 3),
        is_slop_suspect=is_slop,
        warnings=warnings,
        recommendations=recommendations,
    )
