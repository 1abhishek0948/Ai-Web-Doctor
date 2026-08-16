"""Admin configuration for the issues application."""

from __future__ import annotations

from django.contrib import admin

from apps.issues.models import Issue, Verification


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "scan",
        "title",
        "severity",
        "category",
        "source",
        "status",
        "viewport_label",
        "confidence",
        "created_at",
    )
    list_filter = ("severity", "category", "source", "status")
    search_fields = ("title", "description", "selector", "dedup_key")
    readonly_fields = ("dedup_key", "created_at", "viewport_label")
    ordering = ("-created_at",)


@admin.register(Verification)
class VerificationAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "issue",
        "status",
        "old_value",
        "new_value",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("issue__title", "message", "error_message")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
