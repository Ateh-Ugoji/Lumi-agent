from __future__ import annotations


class VoiceExtractionError(RuntimeError):
    """The model did not return a usable voice profile, even after one repair attempt."""
