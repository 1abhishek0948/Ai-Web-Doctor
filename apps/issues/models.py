"""Models for the issues application.

Issues are the normalized output of every detection source:

* ``deterministic`` — objective measurements from the Playwright scanner
* ``accessibility`` — automated axe-core checks
* ``ai`` — Gemini visual/UX reasoning
* ``combined`` — an AI finding merged onto a deterministic/accessibility finding
"""

from __future__ import annotations

from django.db import models

SEVERITIES = ("critical", "high", "medium", "low", "info")

CATEGORIES = (
    "responsive",
    "layout",
    "spacing",
    "typography",
    "color",
    "accessibility",
    "navigation",
    "interaction",
    "performance",
    "ux",
)

SOURCES = ("deterministic", "accessibility", "ai", "combined")

SEVERITY_ORDER = {severity: index for index, severity in enumerate(SEVERITIES)}


class Severity(models.TextChoices):
    CRITICAL = "critical", "Critical"
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"
    INFO = "info", "Info"


class Category(models.TextChoices):
    RESPONSIVE = "responsive", "Responsive"
    LAYOUT = "layout", "Layout"
    SPACING = "spacing", "Spacing"
    TYPOGRAPHY = "typography", "Typography"
    COLOR = "color", "Color"
    ACCESSIBILITY = "accessibility", "Accessibility"
    NAVIGATION = "navigation", "Navigation"
    INTERACTION = "interaction", "Interaction"
    PERFORMANCE = "performance", "Performance"
    UX = "ux", "UX"


class IssueSource(models.TextChoices):
    DETERMINISTIC = "deterministic", "Deterministic"
    ACCESSIBILITY = "accessibility", "Accessibility"
    AI = "ai", "AI"
    COMBINED = "combined", "Combined"


class IssueStatus(models.TextChoices):
    OPEN = "open", "Open"
    CONFIRMED = "confirmed", "Confirmed"
    DISMISSED = "dismissed", "Dismissed"


class Issue(models.Model):
    """A normalized UI problem detected for a scan at a viewport."""

    scan = models.ForeignKey(
        "scans.Scan", on_delete=models.CASCADE, related_name="issues"
    )
    title = models.CharField(max_length=200)
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.MEDIUM, db_index=True
    )
    category = models.CharField(
        max_length=16, choices=Category.choices, default=Category.RESPONSIVE, db_index=True
    )
    source = models.CharField(
        max_length=16, choices=IssueSource.choices, default=IssueSource.DETERMINISTIC
    )
    status = models.CharField(
        max_length=16, choices=IssueStatus.choices, default=IssueStatus.OPEN
    )
    description = models.TextField(blank=True)
    selector = models.CharField(max_length=500, blank=True)
    viewport_width = models.IntegerField(null=True, blank=True)
    viewport_height = models.IntegerField(null=True, blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    ai_explanation = models.TextField(blank=True)
    confidence = models.FloatField(default=0.0)
    dedup_key = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["scan", "severity"]),
            models.Index(fields=["scan", "category"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_severity_display()}: {self.title}"

    @property
    def severity_rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity, len(SEVERITIES))

    @property
    def viewport_label(self) -> str:
        if self.viewport_width and self.viewport_height:
            return f"{self.viewport_width} × {self.viewport_height}"
        return "—"


class VerificationStatus(models.TextChoices):
    VERIFIED = "verified", "Verified"
    IMPROVED = "improved", "Improved"
    FAILED = "failed", "Failed"


class Verification(models.Model):
    """A re-check of a single issue against its live website.

    Part 8: the site is loaded again at the issue's viewport, the same
    deterministic check is re-run, and the measurable result is compared with
    the original. ``old_value`` / ``new_value`` store the before/after
    measurements (e.g. ``"42px"`` → ``"0px"``) and the before/after screenshots
    are kept so a developer can see the difference.
    """

    issue = models.ForeignKey(
        "issues.Issue", on_delete=models.CASCADE, related_name="verifications"
    )
    old_value = models.CharField(max_length=64, blank=True)
    new_value = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16,
        choices=VerificationStatus.choices,
        default=VerificationStatus.FAILED,
        db_index=True,
    )
    message = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    screenshot_before = models.CharField(max_length=500, blank=True)
    screenshot_after = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Verification {self.pk} for issue {self.issue_id}: {self.status}"

    @property
    def has_screenshots(self) -> bool:
        return bool(self.screenshot_before and self.screenshot_after)
