"""One conversation thread per profile. See docs/SCHEMA.md section 6.4."""

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class ChatRole(models.TextChoices):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(models.Model):
    """Append-only. The order by ``id`` is the order of the conversation."""

    profile = models.ForeignKey(
        "profiles.SocialProfile",
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    role = models.CharField(max_length=10, choices=ChatRole.choices)
    content = models.TextField(db_default="", blank=True)
    tool_name = models.CharField(max_length=80, null=True, blank=True)
    tool_call_id = models.CharField(max_length=80, null=True, blank=True)
    tool_calls = models.JSONField(null=True, blank=True)
    tools_used = ArrayField(models.TextField(), null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "chat_messages"
        constraints = [
            models.CheckConstraint(
                condition=Q(role__in=ChatRole.values), name="ck_chat_messages_role"
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "id"], name="ix_chat_messages_profile"),
        ]

    def __str__(self) -> str:
        return f"{self.profile_id} {self.role} {self.id}"
