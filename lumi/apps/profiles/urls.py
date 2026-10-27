from django.urls import path

from apps.profiles import views

urlpatterns = [
    path("profiles", views.ProfileListView.as_view(), name="profiles"),
    path(
        "profiles/<int:profile_id>/select",
        views.ProfileSelectView.as_view(),
        name="profile-select",
    ),
    path(
        "profiles/<int:profile_id>/analytics",
        views.ProfileAnalyticsView.as_view(),
        name="profile-analytics",
    ),
    path(
        "profiles/<int:profile_id>/refresh",
        views.ProfileRefreshView.as_view(),
        name="profile-refresh",
    ),
    path(
        "profiles/<int:profile_id>/alerts/unread",
        views.UnreadAlertsView.as_view(),
        name="profile-alerts-unread",
    ),
    path(
        "profiles/<int:profile_id>/alerts/<int:alert_id>/dismiss",
        views.DismissAlertView.as_view(),
        name="profile-alert-dismiss",
    ),
    path(
        "profiles/<int:profile_id>/listening",
        views.ListeningView.as_view(),
        name="profile-listening",
    ),
]
