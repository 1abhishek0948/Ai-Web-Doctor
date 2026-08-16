"""Single source of truth for issue queries used by the results dashboard.

The dashboard needs severity counts, per-category counts and filtered issue
lists. Centralizing them here keeps ``results_view`` free of ad-hoc queries so
counts and lists can never drift apart.
"""

from __future__ import annotations

from django.db.models import Count, QuerySet

from apps.issues.models import Category, SEVERITIES
from apps.scans.models import Scan

VALID_SEVERITIES = SEVERITIES


class IssueQueryService:
    """Query helpers for the issues of one scan."""

    def __init__(self, scan: Scan) -> None:
        self.scan = scan

    def filtered(self, severity: str = "", category: str = "") -> QuerySet:
        """All issues, optionally narrowed by a valid severity and/or category."""
        qs = self.scan.issues.all()
        if severity in VALID_SEVERITIES:
            qs = qs.filter(severity=severity)
        if category in dict(Category.choices):
            qs = qs.filter(category=category)
        return qs

    def severity_counts(self) -> dict[str, int]:
        """{severity: count} with every known severity present (zero-filled)."""
        counts = {sev: 0 for sev in VALID_SEVERITIES}
        for severity, count in (
            self.scan.issues.values_list("severity")
            .annotate(c=Count("id"))
            .values_list("severity", "c")
        ):
            if severity in counts:
                counts[severity] = count
        return counts

    def category_counts(self) -> dict[str, int]:
        """{category: count} with every known category present (zero-filled)."""
        counts = {key: 0 for key, _ in Category.choices}
        for category, count in (
            self.scan.issues.values_list("category")
            .annotate(c=Count("id"))
            .values_list("category", "c")
        ):
            if category in counts:
                counts[category] = count
        return counts

    def total_count(self) -> int:
        return self.scan.issues.count()