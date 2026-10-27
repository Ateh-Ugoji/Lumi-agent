"""Enums shared by several apps. Adding a value needs a migration in ``profiles``.

See docs/SCHEMA.md section 2.
"""

from django.db import models


class Platform(models.TextChoices):
    X = "x"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"


class IngestSource(models.TextChoices):
    PFM = "pfm"
    XPOZ = "xpoz"
    META = "meta"
    LINKEDIN = "linkedin"
    X = "x"
    IMPORT = "import"
    MANUAL = "manual"


class PostKind(models.TextChoices):
    ORIGINAL = "original"
    REPLY = "reply"
    RETWEET = "retweet"
    QUOTE = "quote"


class JobStatus(models.TextChoices):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
