from django.urls import path

from apps.intelligence import views

urlpatterns = [
    path("repurpose", views.RepurposeView.as_view(), name="repurpose"),
    path("voice/transcribe", views.TranscribeView.as_view(), name="voice-transcribe"),
    path(
        "intelligence/niche-preferences/active",
        views.ActiveNichePreferenceView.as_view(),
        name="active-niche-preference",
    ),
    path(
        "niche-preferences/active",
        views.ActiveNichePreferenceView.as_view(),
        name="active-niche-preference-direct",
    ),
    path(
        "intelligence/niche-reports/ingest",
        views.NicheReportIngestView.as_view(),
        name="niche-report-ingest",
    ),
    path(
        "niche-reports/ingest",
        views.NicheReportIngestView.as_view(),
        name="niche-report-ingest-direct",
    ),
]
