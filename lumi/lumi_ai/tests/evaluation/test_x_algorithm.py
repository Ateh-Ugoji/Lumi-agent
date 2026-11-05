"""Unit tests for X Recommendation Algorithm pre-flight auditor."""

from __future__ import annotations

from lumi_ai.evaluation.x_algorithm import (
    audit_x_post,
    calculate_entropy,
    calculate_shout_ratio,
    score_earlybird_text,
)


def test_calculate_entropy():
    # Repetitive words -> low entropy
    low = calculate_entropy("buy buy buy buy buy buy")
    # Varied vocabulary -> higher entropy
    high = calculate_entropy("Deep research reveals how algorithmic systems evaluate text entropy")
    assert high > low
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0


def test_calculate_shout_ratio():
    assert calculate_shout_ratio("hello world") == 0.0
    assert calculate_shout_ratio("HELLO WORLD") == 1.0
    ratio = calculate_shout_ratio("Hello World")
    assert 0.1 <= ratio <= 0.3


def test_score_earlybird_text():
    short_text = "Hi"
    full_text = (
        "Building an AI company requires solving distribution first. Most founders fail "
        "because they obsess over models rather than finding high-leverage workflows."
    )
    score_short = score_earlybird_text(short_text)
    score_full = score_earlybird_text(full_text)
    assert score_full["text_score"] > score_short["text_score"]
    assert score_full["entropy_score"] > score_short["entropy_score"]


def test_audit_x_post_with_body_link_penalty():
    text_with_link = (
        "Check out our new framework for building agentic AI products! "
        "Read the full breakdown here: https://example.com/blog/agentic-ai"
    )
    audit = audit_x_post(text_with_link)
    assert audit.has_body_link is True
    assert any("External URL in tweet body" in w for w in audit.warnings)
    assert any("Move external links" in r for r in audit.recommendations)
    # Composite score penalized heavily
    assert audit.composite_score < 75.0


def test_audit_x_post_with_multiple_hashtags():
    text_with_hashtags = (
        "Building agents with LLMs is the future of software #AI #MachineLearning #Tech #Coding"
    )
    audit = audit_x_post(text_with_hashtags)
    assert audit.num_hashtags == 4
    assert any("4 hashtags detected" in w for w in audit.warnings)


def test_audit_x_post_conversational_question_boost():
    no_question = "Most founders make the mistake of building before talking to 50 customers."
    with_question = (
        "Most founders make the mistake of building before talking to 50 customers. "
        "What was your biggest surprise from customer interviews?"
    )
    audit_no_q = audit_x_post(no_question)
    audit_with_q = audit_x_post(with_question)
    assert audit_with_q.has_question is True
    assert audit_with_q.predicted_reply_prob > audit_no_q.predicted_reply_prob
    assert audit_with_q.composite_score > audit_no_q.composite_score


def test_audit_x_post_shout_damping():
    screaming = "EVERYONE MUST STOP WHAT THEY ARE DOING AND LOOK AT THIS INSANE AI TOOL RIGHT NOW"
    audit = audit_x_post(screaming)
    assert audit.shout_score < 0.5
    assert any("Excessive uppercase" in w for w in audit.warnings)


def test_audit_x_post_slop_detection():
    slop = "In today's fast-paced digital world, let's dive into how AI is a true game-changer."
    audit = audit_x_post(slop)
    assert audit.is_slop_suspect is True
    assert any("cliché phrase" in w for w in audit.warnings)
