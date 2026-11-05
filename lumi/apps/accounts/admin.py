from django.contrib import admin
from django.contrib.auth.models import Group

from apps.accounts.models import AuthToken, User
from apps.core.admin import SafeModelAdmin


@admin.register(User)
class UserAdmin(SafeModelAdmin):
    # The password hash is never shown.
    exclude = ("password", "groups", "user_permissions")
    list_display = (
        "id",
        "email",
        "display_name",
        "is_active",
        "is_staff",
        "created_at",
    )
    list_filter = ("is_active", "is_staff")
    search_fields = ("email", "display_name")
    ordering = ("-id",)


@admin.register(AuthToken)
class AuthTokenAdmin(SafeModelAdmin):
    # Only a sha256 of the key is stored; hiding it anyway keeps lookups by hash impossible from the UI.
    exclude = ("key_hash",)
    list_display = ("id", "user", "name", "created_at", "last_used_at", "expires_at")
    search_fields = ("user__email", "name")
    ordering = ("-id",)


# Groups and per-user permissions are not used: access is "is_staff" plus the read-only admins.
admin.site.unregister(Group)
