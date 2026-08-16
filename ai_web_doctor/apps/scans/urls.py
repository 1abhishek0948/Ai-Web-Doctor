"""Web URL configuration for the scans application."""

from __future__ import annotations

from django.urls import path

from apps.scans import views

app_name = "scans"

urlpatterns = [
    path("scans/", views.scan_list_view, name="scan-list"),
    path("scans/<int:scan_id>/", views.scan_detail_view, name="scan-detail"),
    path("scans/<int:scan_id>/results/", views.results_view, name="scan-results"),
    path("scans/<int:scan_id>/progress/", views.scan_progress_view, name="scan-progress"),
    path(
        "scans/<int:scan_id>/issues/<int:issue_id>/",
        views.issue_detail_view,
        name="issue-detail",
    ),
    path(
        "scans/<int:scan_id>/issues/<int:issue_id>/fix/",
        views.issue_fix_view,
        name="issue-fix",
    ),
    path(
        "scans/<int:scan_id>/issues/<int:issue_id>/verify/",
        views.issue_verify_view,
        name="issue-verify",
    ),
]
