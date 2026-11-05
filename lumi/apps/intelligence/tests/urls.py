"""Test urlconf: ``config/urls.py`` is ARCHITECT's, so this app's routes are mounted here."""

from django.urls import include, path

urlpatterns = [path("api/v1/", include("apps.intelligence.urls"))]
