from django.db import models
from django.db.models.functions import Now


class TimestampedModel(models.Model):
    """``created_at`` and ``updated_at`` for tables that change after insert.

    ``created_at`` has a server-side default so a raw INSERT is valid too.
    """

    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now(), editable=False)

    class Meta:
        abstract = True
