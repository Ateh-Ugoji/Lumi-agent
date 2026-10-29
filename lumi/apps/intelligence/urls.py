from django.urls import path

from apps.intelligence import views

urlpatterns = [
    path("repurpose", views.RepurposeView.as_view(), name="repurpose"),
    path("voice/transcribe", views.TranscribeView.as_view(), name="voice-transcribe"),
]
