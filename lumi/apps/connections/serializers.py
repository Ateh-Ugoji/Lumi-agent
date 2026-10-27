"""Request and response shapes. No serializer here ever reads a token column."""

from __future__ import annotations

from rest_framework import serializers

from .handles.ranking import PLATFORMS
from .models import ConnectedAccount


class ConnectRequestSerializer(serializers.Serializer):
    profile_id = serializers.IntegerField(required=False, min_value=1)
    redirect_after = serializers.CharField(
        required=False, allow_blank=True, max_length=500
    )
    platform = serializers.RegexField(
        r"^[a-z_]{1,20}$",
        required=False,
        help_text="Solo para pfm: la red social que se conecta.",
    )


class CallbackRequestSerializer(serializers.Serializer):
    state = serializers.CharField(max_length=256)
    code = serializers.CharField(
        max_length=2000, trim_whitespace=False, required=False, allow_blank=True
    )
    error = serializers.CharField(max_length=200, required=False, allow_blank=True)


class CallbackResponseSerializer(serializers.Serializer):
    provider = serializers.CharField()
    connected = serializers.BooleanField()
    accounts = serializers.IntegerField()
    redirect_after = serializers.CharField()


class LinkRequestSerializer(serializers.Serializer):
    account_id = serializers.CharField(max_length=128)
    profile_id = serializers.IntegerField(min_value=1)


class ConnectResponseSerializer(serializers.Serializer):
    authorize_url = serializers.URLField()


class ConnectedAccountSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="external_account_id", read_only=True)
    profile_id = serializers.IntegerField(
        source="social_profile_id", read_only=True, allow_null=True
    )

    class Meta:
        model = ConnectedAccount
        fields = [
            "id",
            "platform",
            "display_name",
            "handle",
            "status",
            "profile_id",
            "scopes",
            "expires_at",
            "last_refreshed_at",
            "last_error",
        ]
        read_only_fields = fields


class StatusSerializer(serializers.Serializer):
    provider = serializers.CharField()
    configured = serializers.BooleanField()
    connected = serializers.BooleanField()
    stale = serializers.BooleanField()
    accounts = ConnectedAccountSerializer(many=True)
    details = serializers.DictField(
        required=False,
        help_text="Datos propios del proveedor que no son cuentas (Google: scopes, caducidad).",
    )


class LinkResponseSerializer(serializers.Serializer):
    provider = serializers.CharField()
    profile_id = serializers.IntegerField()
    account = ConnectedAccountSerializer()
    replaced_account_id = serializers.CharField(allow_null=True)
    moved_from_profile_id = serializers.IntegerField(allow_null=True)


class DisconnectSerializer(serializers.Serializer):
    provider = serializers.CharField()
    disconnected = serializers.IntegerField()
    remote_revoked = serializers.IntegerField()


_NETWORKS = ", ".join(PLATFORMS)


class PlatformField(serializers.CharField):
    """``platform=instagram``: required, one known network, lowercased and stripped like
    ``platforms``. Every refusal names the valid networks."""

    default_error_messages = {
        "required": f"Indica la red: {_NETWORKS}.",
        "null": f"Indica la red: {_NETWORKS}.",
        "blank": f"Indica la red: {_NETWORKS}.",
        "unknown": f"Red no válida: {{name}}. Redes: {_NETWORKS}.",
    }

    def to_internal_value(self, data):
        name = super().to_internal_value(data).strip().lower()
        if not name:
            self.fail("blank")
        if name not in PLATFORMS:
            self.fail("unknown", name=name)
        return name


class PlatformsField(serializers.CharField):
    """``platforms=x,instagram``: required, at least one network, every name a known one.

    A missing, empty or unknown value is a ``400 validation_error``, never a silent fall back
    to X. The value that reaches the view is the lowercased, comma-joined list.
    """

    default_error_messages = {
        "required": f"Indica al menos una red: {_NETWORKS}.",
        "null": f"Indica al menos una red: {_NETWORKS}.",
        "blank": f"Indica al menos una red: {_NETWORKS}.",
    }

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("max_length", 100)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        names = [p.strip().lower() for p in super().to_internal_value(data).split(",")]
        names = [n for n in names if n]
        if not names:
            raise serializers.ValidationError(f"Indica al menos una red: {_NETWORKS}.")
        unknown = [n for n in names if n not in PLATFORMS]
        if unknown:
            raise serializers.ValidationError(
                f"Red no válida: {', '.join(unknown)}. Redes: {_NETWORKS}."
            )
        return ",".join(names)


class HandleSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=100
    )
    context = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=300
    )
    platforms = PlatformsField()


class HandleSavedQuerySerializer(serializers.Serializer):
    platforms = PlatformsField()


class HandleRowSerializer(serializers.Serializer):
    handle = serializers.CharField()
    display_name = serializers.CharField(allow_blank=True)
    avatar_url = serializers.CharField(allow_blank=True)
    followers = serializers.IntegerField(allow_null=True)
    source = serializers.ChoiceField(choices=["db", "cache", "live"])
    platform = serializers.CharField()


class HandleSearchResponseSerializer(serializers.Serializer):
    query = serializers.CharField()
    results = HandleRowSerializer(many=True)
    live = serializers.BooleanField()
    refreshed = serializers.BooleanField()
    reason = serializers.CharField(allow_null=True)
    context = serializers.CharField(allow_blank=True)
    platforms = serializers.ListField(child=serializers.CharField())
    platform_reasons = serializers.DictField(
        child=serializers.CharField(allow_null=True)
    )


class HandleSavedResponseSerializer(serializers.Serializer):
    results = HandleRowSerializer(many=True)
    count = serializers.IntegerField()


class HandleSelectSerializer(serializers.Serializer):
    """Only the handle. A photo, name or follower count in the body is ignored, never stored."""

    handle = serializers.CharField(min_length=1, max_length=101)
    platform = PlatformField()
    selected_query = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=100
    )


class HandleSelectResponseSerializer(serializers.Serializer):
    remembered = serializers.BooleanField()
    handle = serializers.CharField()
    platform = serializers.CharField()


class HandleStatsSerializer(serializers.Serializer):
    live_enabled = serializers.BooleanField()
    live_budget = serializers.IntegerField()
    live_budget_by_platform = serializers.DictField(child=serializers.IntegerField())
    daily_cap_user = serializers.IntegerField()
    daily_cap_global = serializers.IntegerField()
    credits_spent_24h = serializers.IntegerField()
    cache_ttl_minutes = serializers.IntegerField()
    saved_handles = serializers.IntegerField()
    remembered_handles = serializers.IntegerField()
    cached_searches = serializers.IntegerField()
    available_platforms = serializers.ListField(child=serializers.DictField())


class PublishRequestSerializer(serializers.Serializer):
    profile_id = serializers.IntegerField(min_value=1)
    platform = serializers.ChoiceField(
        choices=["x", "instagram", "tiktok", "linkedin", "facebook"]
    )
    text = serializers.CharField(
        required=False, allow_blank=False, max_length=5000, trim_whitespace=True
    )
    attempt_id = serializers.IntegerField(required=False, min_value=1)
    link = serializers.URLField(required=False, allow_blank=True, max_length=2000)
    confirm = serializers.BooleanField(required=False, default=False)
    dry_run = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if "text" not in attrs and "attempt_id" not in attrs:
            raise serializers.ValidationError("Envía text o attempt_id.")
        return attrs


class PublishResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["done", "dry_run"])
    dry_run = serializers.BooleanField()
    replayed = serializers.BooleanField()
    job_id = serializers.IntegerField(allow_null=True)
    platform = serializers.CharField()
    external_post_id = serializers.CharField(allow_null=True)
    url = serializers.CharField(allow_null=True)
    estimated_cost_usd = serializers.FloatField(allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField())
