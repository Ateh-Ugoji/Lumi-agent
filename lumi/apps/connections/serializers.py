"""Request and response shapes. No serializer here ever reads a token column."""

from __future__ import annotations

from rest_framework import serializers

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


class DisconnectSerializer(serializers.Serializer):
    provider = serializers.CharField()
    disconnected = serializers.IntegerField()
    remote_revoked = serializers.IntegerField()


class HandleSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=100
    )
    context = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=300
    )
    platforms = serializers.CharField(
        required=False, allow_blank=True, default="x", max_length=100
    )


class HandleSavedQuerySerializer(serializers.Serializer):
    platforms = serializers.CharField(
        required=False, allow_blank=True, default="x", max_length=100
    )


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
    handle = serializers.CharField(min_length=1, max_length=101)
    platform = serializers.ChoiceField(
        choices=["x", "instagram", "tiktok", "linkedin", "facebook"], default="x"
    )
    display_name = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=200
    )
    avatar_url = serializers.URLField(
        required=False, allow_blank=True, default="", max_length=2000
    )
    followers = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=0
    )
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
    credits_spent_24h = serializers.IntegerField()
    cache_ttl_minutes = serializers.IntegerField()
    saved_handles = serializers.IntegerField()
    remembered_handles = serializers.IntegerField()
    cached_searches = serializers.IntegerField()
    available_platforms = serializers.ListField(child=serializers.DictField())
