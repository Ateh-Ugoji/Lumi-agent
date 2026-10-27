"""Test urlconf. ARCHITECT mounts the real one in ``config/urls.py``."""

from django.urls import include, path

urlpatterns = [path("api/v1/", include("apps.connections.urls"))]
