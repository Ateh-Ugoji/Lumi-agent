"""Routes of the connections app. Mount under ``api/v1/`` in ``config/urls.py``.

The segment ``connections/`` is part of these routes, so one include is enough::

    path("api/v1/", include("apps.connections.urls"))
"""

from django.urls import path

from . import views

urlpatterns = [
    path(
        "connections/<str:provider>/connect",
        views.ConnectView.as_view(),
        name="connections-connect",
    ),
    path(
        "connections/<str:provider>/callback",
        views.CallbackView.as_view(),
        name="connections-callback",
    ),
    path(
        "connections/<str:provider>/status",
        views.ProviderView.as_view(),
        name="connections-status",
    ),
    path(
        "connections/<str:provider>",
        views.ProviderView.as_view(),
        name="connections-provider",
    ),
]
