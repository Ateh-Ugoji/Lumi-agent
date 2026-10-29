from django.contrib import admin

from apps.core.admin import SafeModelAdmin
from apps.profiles.models import (
    Alert,
    HandleSnapshot,
    ListeningKeyword,
    ListeningMatch,
    MetricSnapshot,
    PollConfig,
    Post,
    PostMedia,
    ProfileBaseline,
    SocialHandle,
    SocialProfile,
)


@admin.register(SocialHandle)
class SocialHandleAdmin(SafeModelAdmin):
    list_display = (
        "id",
        "platform",
        "handle_normalized",
        "follower_count",
        "origin",
        "last_seen_at",
    )
    list_filter = ("platform", "origin")
    search_fields = ("handle_normalized", "handle_display", "display_name")
    ordering = ("-id",)


@admin.register(HandleSnapshot)
class HandleSnapshotAdmin(SafeModelAdmin):
    list_display = ("id", "handle", "captured_at", "followers", "source")
    ordering = ("-id",)


@admin.register(SocialProfile)
class SocialProfileAdmin(SafeModelAdmin):
    list_display = ("id", "user", "handle", "timezone", "bootstrapped_at")
    search_fields = ("user__email", "handle__handle_normalized")
    ordering = ("-id",)


@admin.register(ProfileBaseline)
class ProfileBaselineAdmin(SafeModelAdmin):
    list_display = (
        "id",
        "profile",
        "window_days",
        "n_posts",
        "baseline_reliable",
        "computed_at",
    )
    list_filter = ("baseline_reliable",)
    ordering = ("-id",)


@admin.register(PollConfig)
class PollConfigAdmin(SafeModelAdmin):
    list_display = ("id", "profile", "interval_minutes", "is_active", "last_polled_at")
    list_filter = ("is_active",)


@admin.register(ListeningKeyword)
class ListeningKeywordAdmin(SafeModelAdmin):
    list_display = ("id", "profile", "keyword", "created_at")
    search_fields = ("keyword",)
    ordering = ("-id",)


@admin.register(Post)
class PostAdmin(SafeModelAdmin):
    list_display = ("id", "author", "kind", "published_at", "is_stub", "source")
    list_filter = ("kind", "source", "is_stub", "is_deleted_suspect")
    search_fields = ("platform_post_id", "caption")
    ordering = ("-id",)


@admin.register(PostMedia)
class PostMediaAdmin(SafeModelAdmin):
    list_display = ("id", "post", "position", "kind")
    list_filter = ("kind",)
    ordering = ("-id",)


@admin.register(MetricSnapshot)
class MetricSnapshotAdmin(SafeModelAdmin):
    list_display = ("id", "post", "captured_at", "source", "likes", "comments", "views")
    list_filter = ("source",)
    ordering = ("-id",)


@admin.register(Alert)
class AlertAdmin(SafeModelAdmin):
    list_display = ("id", "profile", "post", "kind", "trigger", "status", "created_at")
    list_filter = ("kind", "trigger", "status")
    ordering = ("-id",)


@admin.register(ListeningMatch)
class ListeningMatchAdmin(SafeModelAdmin):
    list_display = ("id", "profile", "post", "score", "discovered_at")
    ordering = ("-id",)
