"""Models for the scans application."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ScanStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    PARTIAL = "partial", "Partial"


class AIStatus(models.TextChoices):
    """Machine-readable AI analysis state for a scan.

    ``pending``/``running`` describe lifecycle, ``completed`` success, and the
    rest describe why AI findings are missing so the dashboard can distinguish
    "analyzed, no issues" from "analysis never happened".
    """

    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    UNAVAILABLE = "unavailable", "Unavailable"
    FAILED = "failed", "Failed"
    RATE_LIMITED = "rate_limited", "Rate limited"
    SKIPPED = "skipped", "Skipped"


class ProgressStage(models.TextChoices):
    """Ordered progress stages surfaced to the UI during a scan."""

    QUEUED = "queued", "Queued"
    VALIDATING = "validating", "Validating URL"
    LAUNCHING = "launching", "Launching browser"
    LOADING = "loading", "Loading website"
    CAPTURING = "capturing", "Capturing screenshots"
    RESPONSIVE = "responsive", "Checking responsive layout"
    ACCESSIBILITY = "accessibility", "Checking accessibility"
    AI_ANALYSIS = "ai_analysis", "Running AI analysis"
    REPORTING = "reporting", "Building report"
    COMPLETE = "complete", "Complete"

    @classmethod
    def ordered(cls) -> list[str]:
        return [choice[0] for choice in cls.choices]


class Scan(models.Model):
    """A website scan request and its lifecycle state."""

    url = models.URLField(max_length=2048)
    normalized_url = models.URLField(max_length=2048, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scans",
    )
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ScanStatus.choices,
        default=ScanStatus.QUEUED,
        db_index=True,
    )
    progress_stage = models.CharField(
        max_length=32,
        choices=ProgressStage.choices,
        default=ProgressStage.QUEUED,
    )
    health_score = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    ai_message = models.TextField(blank=True)
    ai_status = models.CharField(
        max_length=16,
        choices=AIStatus.choices,
        default=AIStatus.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Scan {self.pk} of {self.normalized_url or self.url}"

    def set_running(self) -> None:
        self.status = ScanStatus.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])

    def set_completed(self) -> None:
        self.status = ScanStatus.COMPLETED
        self.progress_stage = ProgressStage.COMPLETE
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "progress_stage", "completed_at"])

    def set_partial(self) -> None:
        self.status = ScanStatus.PARTIAL
        self.progress_stage = ProgressStage.COMPLETE
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "progress_stage", "completed_at"])

    def set_failed(self, message: str) -> None:
        self.status = ScanStatus.FAILED
        self.error_message = message
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at"])

    def set_progress(self, stage: str) -> None:
        self.progress_stage = stage
        self.save(update_fields=["progress_stage"])


class Screenshot(models.Model):
    """A screenshot captured for a scan at a specific viewport."""

    scan = models.ForeignKey(Scan, on_delete=models.CASCADE, related_name="screenshots")
    viewport_width = models.IntegerField()
    viewport_height = models.IntegerField()
    path = models.CharField(max_length=500)
    file_size = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["viewport_width", "viewport_height"]

    def __str__(self) -> str:
        return f"Screenshot {self.pk} {self.viewport_width}x{self.viewport_height}"


class PageMetric(models.Model):
    """A named layout metric captured for a scan at a viewport.

    Stored as flat key/value rows so new metrics don't require migrations.
    """

    scan = models.ForeignKey(Scan, on_delete=models.CASCADE, related_name="metrics")
    viewport_width = models.IntegerField()
    viewport_height = models.IntegerField()
    key = models.CharField(max_length=64)
    value = models.CharField(max_length=255)

    class Meta:
        ordering = ["viewport_width", "viewport_height", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["scan", "viewport_width", "viewport_height", "key"],
                name="unique_page_metric",
            )
        ]

    def __str__(self) -> str:
        return f"{self.key}={self.value}"
