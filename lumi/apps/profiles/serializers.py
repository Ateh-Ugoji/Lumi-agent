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


TRENDS_DEFAULT = 50
TRENDS_MAX = 200
MAX_HANDLES = 20


class TrendMatchesQuerySerializer(serializers.Serializer):
    profile_id = serializers.IntegerField()
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=TRENDS_MAX, default=TRENDS_DEFAULT
    )


class ScanTrendsSerializer(serializers.Serializer):
    profile_id = serializers.IntegerField()
    handles = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_null=True,
        max_length=MAX_HANDLES,
    )
    min_likes = serializers.IntegerField(required=False, min_value=0, default=20)
