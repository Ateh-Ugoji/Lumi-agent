"""Request bodies of the profile routes. Responses are plain dicts built by the services."""

from rest_framework import serializers

from apps.core.choices import Platform
from apps.profiles.services import KEYWORD_MAX, MAX_INTERVAL, MIN_INTERVAL

MAX_KEYWORDS = 50


class CreateProfileSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=Platform.choices)
    handle = serializers.CharField(max_length=100)


class ListeningSerializer(serializers.Serializer):
    keywords = serializers.ListField(
        child=serializers.CharField(max_length=KEYWORD_MAX, allow_blank=True),
        max_length=MAX_KEYWORDS,
    )
    enabled = serializers.BooleanField()
    interval_minutes = serializers.IntegerField(
        required=False, allow_null=True, min_value=MIN_INTERVAL, max_value=MAX_INTERVAL
    )
