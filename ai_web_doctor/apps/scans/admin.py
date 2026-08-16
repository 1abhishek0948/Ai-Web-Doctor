"""Admin configuration for the scans application."""

from django.contrib import admin

from apps.scans.models import PageMetric, Scan, Screenshot


class ScreenshotInline(admin.TabularInline):
    model = Screenshot
    extra = 0


class PageMetricInline(admin.TabularInline):
    model = PageMetric
    extra = 0


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = ("pk", "normalized_url", "status", "progress_stage", "created_at")
    list_filter = ("status",)
    search_fields = ("url", "normalized_url")
    readonly_fields = ("created_at", "started_at", "completed_at")
    inlines = [ScreenshotInline, PageMetricInline]


@admin.register(Screenshot)
class ScreenshotAdmin(admin.ModelAdmin):
    list_display = ("pk", "scan", "viewport_width", "viewport_height", "file_size")
