"""Tests for the Part 5 results dashboard and Part 7 fix endpoint views."""

from __future__ import annotations

from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.ai.service import AI_UNAVAILABLE_MESSAGE, FixResult
from apps.issues.models import Issue
from apps.scans.models import Scan, ScanStatus


class ResultsDashboardTests(TestCase):
    def setUp(self) -> None:
        self.scan = Scan.objects.create(
            url="https://example.com",
            normalized_url="https://example.com/",
            status=ScanStatus.COMPLETED,
            health_score=72,
        )
        self.critical = Issue.objects.create(
            scan=self.scan,
            title="Horizontal overflow on mobile",
            severity="critical",
            category="responsive",
            viewport_width=320,
            viewport_height=800,
        )
        Issue.objects.create(
            scan=self.scan,
            title="Low contrast button label",
            severity="low",
            category="accessibility",
            viewport_width=375,
            viewport_height=812,
        )

    def test_scan_list_renders(self):
        response = self.client.get(reverse("scans:scan-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your scans")
        self.assertContains(response, "example.com")

    def test_results_dashboard_renders(self):
        response = self.client.get(reverse("scans:scan-results", args=[self.scan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UI Health")
        self.assertContains(response, "Horizontal overflow on mobile")
        self.assertContains(response, "Responsive")
        self.assertContains(response, "Accessibility")

    def test_results_severity_counts(self):
        response = self.client.get(reverse("scans:scan-results", args=[self.scan.pk]))
        self.assertContains(response, "?severity=critical")
        self.assertContains(response, "?severity=low")

    def test_results_severity_filter(self):
        url = reverse("scans:scan-results", args=[self.scan.pk]) + "?severity=low"
        response = self.client.get(url)
        self.assertContains(response, "Low contrast button label")
        self.assertNotContains(response, "Horizontal overflow on mobile")

    def test_results_category_filter(self):
        url = reverse("scans:scan-results", args=[self.scan.pk]) + "?category=responsive"
        response = self.client.get(url)
        self.assertContains(response, "Horizontal overflow on mobile")
        self.assertNotContains(response, "Low contrast button label")

    def test_visual_categories_analyzed_without_ai(self):
        self.scan.ai_message = AI_UNAVAILABLE_MESSAGE
        self.scan.save(update_fields=["ai_message"])
        response = self.client.get(reverse("scans:scan-results", args=[self.scan.pk]))
        self.assertNotContains(response, "Not analyzed")

    def test_issue_detail_renders(self):
        response = self.client.get(
            reverse("scans:issue-detail", args=[self.scan.pk, self.critical.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Horizontal overflow on mobile")
        self.assertContains(response, "Generate Fix")
        self.assertContains(response, "Analyzing issue")
        self.assertContains(response, "Generating fix")
        self.assertContains(response, "suggestion only")


class IssueFixViewTests(TestCase):
    def setUp(self) -> None:
        self.scan = Scan.objects.create(
            url="https://example.com",
            normalized_url="https://example.com/",
            status=ScanStatus.COMPLETED,
        )
        self.issue = Issue.objects.create(
            scan=self.scan,
            title="Header overlaps content",
            severity="high",
            category="layout",
            viewport_width=375,
            viewport_height=812,
        )
        self.url = reverse("scans:issue-fix", args=[self.scan.pk, self.issue.pk])

    def test_fix_success_partial(self):
        result = FixResult(
            ok=True,
            explanation="The header needs to reserve space.",
            recommended_change="Add top padding to the body.",
            code="body { padding-top: 56px; }",
            language="css",
        )
        with mock.patch("apps.scans.views.generate_fix", return_value=result):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Copy Fix")
        self.assertContains(response, "CSS")
        self.assertContains(response, "padding-top")
        self.assertContains(response, "suggestion only")

    def test_fix_error_partial(self):
        result = FixResult(ok=False, error="The AI could not be reached. Please try again.")
        with mock.patch("apps.scans.views.generate_fix", return_value=result):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "could not be reached")

    def test_fix_requires_post(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
