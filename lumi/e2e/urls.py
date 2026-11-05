"""The real routes plus the simulated provider consent pages (``/__sim__/...``)."""

from django.urls import path

from config.urls import *
from config.urls import urlpatterns as real_patterns
from e2e import sim

urlpatterns = [
    path("__sim__/meta/pages", sim.meta_pages, name="sim-meta-pages"),
    path("__sim__/pfm/consent", sim.pfm_consent, name="sim-pfm-consent"),
    *real_patterns,
]
