"""Serializers for intelligence app endpoints."""

from __future__ import annotations

from rest_framework import serializers

from apps.intelligence.models import (
    ReportOrigin,
    ReportStatus,
)


class ActiveNichePreferenceSerializer(serializers.Serializer):
    profile_id = serializers.IntegerField()
    email = serializers.EmailField()
    niche_key = serializers.CharField()
    title = serializers.CharField()
    keywords = serializers.ListField(child=serializers.CharField())
    handles = serializers.ListField(child=serializers.CharField())
    is_active = serializers.BooleanField()


class IngestPostItemSerializer(serializers.Serializer):
    platform_post_id = serializers.CharField(max_length=64)
    platform = serializers.CharField(max_length=20)
    author_handle = serializers.CharField(max_length=100)
    author_display_name = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    author_avatar_url = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    caption = serializers.CharField(allow_blank=True, default="")
    url = serializers.CharField(allow_blank=True, default="")
    published_at = serializers.DateTimeField(required=False, allow_null=True)
    likes = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    comments = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    reposts = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    views = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    format = serializers.CharField(max_length=20, required=False, default="single")


class IngestFrameworkItemSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    description = serializers.CharField(allow_blank=True, default="")
    lift = serializers.FloatField(required=False, allow_null=True)
    confidence = serializers.FloatField(
        required=False, allow_null=True, min_value=0.0, max_value=1.0
    )
    ordinal = serializers.IntegerField(min_value=0, default=0)
    payload = serializers.JSONField(required=False, allow_null=True, default=dict)
    evidence_platform_post_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )


class NicheReportIngestSerializer(serializers.Serializer):
    profile_id = serializers.IntegerField(min_value=1)
    niche = serializers.CharField(max_length=200)
    query = serializers.CharField(allow_blank=True, default="")
    origin = serializers.ChoiceField(
        choices=ReportOrigin.choices, default=ReportOrigin.PIPELINE
    )
    status = serializers.ChoiceField(
        choices=ReportStatus.choices, default=ReportStatus.OK
    )
    posts_analyzed = serializers.IntegerField(min_value=0, default=0)
    winner_count = serializers.IntegerField(min_value=0, default=0)
    peers_analyzed = serializers.IntegerField(min_value=0, default=0)
    report = serializers.JSONField(required=False, default=dict)
    posts = IngestPostItemSerializer(many=True, required=False, default=list)
    frameworks = IngestFrameworkItemSerializer(many=True, required=False, default=list)
