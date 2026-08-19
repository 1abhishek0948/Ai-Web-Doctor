"""Root URL configuration for AI Web Doctor."""

from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as static_serve
from rest_framework.routers import DefaultRouter

from django.http import HttpResponse
from apps.accounts.views import landing

def health_check(request):
    return HttpResponse("OK")

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
    path("health/", health_check, name="health_check"),
]

# Serve user-uploaded media files (screenshots, scan results).
# In development, Django's static() helper handles this.
# In production on Render Free Tier (no external storage), we fall back to
# django.views.static.serve. This is acceptable for low-traffic free-tier
# use; for higher traffic, switch to S3/Cloudinary and remove this block.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            static_serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
