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
