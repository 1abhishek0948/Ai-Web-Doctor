"""Root URL configuration for AI Web Doctor."""

from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import landing

router = DefaultRouter()

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", landing, name="landing"),
    path("", include("apps.seo.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.scans.urls")),
    path("api/", include(router.urls)),
    path("api/", include("apps.scans.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
