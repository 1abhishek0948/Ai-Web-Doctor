"""Django REST Framework API URL configuration for the scans application.

Part 1 exposes only the health endpoint. Scan CRUD endpoints arrive with the
scanner (Part 2+).
"""

from __future__ import annotations

from django.urls import path

from apps.scans.views import health_view

urlpatterns = [
    path("health/", health_view, name="api-health"),
]
