"""The cold-start questionnaire: what is asked when there are too few posts to learn from."""

from __future__ import annotations

STYLE_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("topics", "What do you mainly post about, and who is it for?"),
    (
        "tone",
        "How would a friend describe the way you write (blunt, warm, funny, formal...)?",
    ),
    (
        "length",
        "How long are your posts usually: one line, a short paragraph, long form?",
    ),
    ("emoji", "Do you use emojis or hashtags? Which ones, and where?"),
    ("never", "What would you never write or never sound like?"),
    (
        "example",
        "Paste one post of yours (or by someone else) that sounds exactly like you.",
    ),
)

STYLE_QUESTION_KEYS = frozenset(key for key, _ in STYLE_QUESTIONS)
