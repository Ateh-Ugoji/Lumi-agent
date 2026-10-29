from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.health import health
from apps.core.job_views import JobView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", health, name="health"),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.profiles.urls")),
    path("api/v1/", include("apps.chat.urls")),
    path("api/v1/jobs/<uuid:job_id>", JobView.as_view(), name="job"),
    path("api/v1/", include("apps.connections.urls")),
    path("api/v1/", include("apps.intelligence.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

handler404 = "apps.core.errors.not_found_view"
handler500 = "apps.core.errors.server_error_view"
