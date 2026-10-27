from django.contrib import admin

from apps.chat.models import ChatMessage
from apps.core.admin import SafeModelAdmin


@admin.register(ChatMessage)
class ChatMessageAdmin(SafeModelAdmin):
    list_display = ("id", "profile", "role", "tool_name", "created_at")
    list_filter = ("role",)
    ordering = ("-id",)
