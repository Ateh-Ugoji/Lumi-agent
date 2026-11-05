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
MAX_KEYWORDS = 5


class TrendMatchesQuerySerializer(serializers.Serializer):
    profile_id = serializers.IntegerField()
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=TRENDS_MAX, default=TRENDS_DEFAULT
    )
    keyword = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=100,
        help_text="Only matches found by this keyword search. Omit for every match.",
    )


class TrendMatchSerializer(serializers.Serializer):
    """Shape of one ``GET /trends/matches`` item. Documents the response; the services build it."""

    id = serializers.IntegerField()
    profile_id = serializers.IntegerField()
    platform = serializers.ChoiceField(choices=Platform.choices)
    platform_post_id = serializers.CharField()
    author_handle = serializers.CharField()
    caption = serializers.CharField()
    platform_url = serializers.CharField()
    author_avatar_url = serializers.CharField(
        allow_null=True,
        help_text="Picture stored for the author (http or https). null: unknown, the client falls back.",
    )
    metrics = serializers.DictField(
        child=serializers.IntegerField(allow_null=True), allow_null=True
    )
    discovered_at = serializers.DateTimeField()
    keyword = serializers.CharField(
        allow_null=True,
        help_text="The keyword search that found the post. null: a scan of tracked accounts found it.",
    )


class TrendMatchesResponseSerializer(serializers.Serializer):
    matches = TrendMatchSerializer(many=True)


class ScanTrendsSerializer(serializers.Serializer):
    profile_id = serializers.IntegerField()
    handles = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_null=True,
        max_length=MAX_HANDLES,
    )
    keywords = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_null=True,
        max_length=MAX_KEYWORDS,
        help_text="Keyword searches to run. Omit to use the keywords saved in listening.",
    )
    min_likes = serializers.IntegerField(required=False, min_value=0, default=20)
