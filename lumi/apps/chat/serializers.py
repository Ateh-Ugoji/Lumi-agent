from rest_framework import serializers

MESSAGE_MAX = 8000
HISTORY_DEFAULT = 50
HISTORY_MAX = 200


class ChatRequestSerializer(serializers.Serializer):
    profile_id = serializers.IntegerField()
    message = serializers.CharField(max_length=MESSAGE_MAX, trim_whitespace=True)


class TitleRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=MESSAGE_MAX, trim_whitespace=True)


class HistoryQuerySerializer(serializers.Serializer):
    profile_id = serializers.IntegerField()
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=HISTORY_MAX, default=HISTORY_DEFAULT
    )
    before = serializers.IntegerField(required=False, min_value=1)
