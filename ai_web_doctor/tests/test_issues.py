"""Tests for the Issue model and deterministic finding persistence (Part 3)."""

from __future__ import annotations

from django.test import TestCase

from apps.issues.models import Issue
from apps.scans.models import Scan, ScanStatus
from apps.scans.services import _compute_dedup_key, _persist_findings


class IssueModelTests(TestCase):
    def setUp(self) -> None:
        self.scan = Scan.objects.create(
            url="https://example.com",
            normalized_url="https://example.com/",
            status=ScanStatus.COMPLETED,
        )

    def test_severity_rank_ordering(self):
        issue = Issue.objects.create(
            scan=self.scan, title="x", severity="critical"
        )
        low = Issue(severity="low")
        self.assertLess(issue.severity_rank, low.severity_rank)

    def test_viewport_label(self):
        issue = Issue.objects.create(
            scan=self.scan,
            title="x",
            severity="medium",
            viewport_width=375,
            viewport_height=812,
        )
        self.assertEqual(issue.viewport_label, "375 × 812")


class PersistFindingsTests(TestCase):
    def setUp(self) -> None:
        self.scan = Scan.objects.create(
            url="https://example.com",
            normalized_url="https://example.com/",
        )

    def _finding(self, check="overflow", selector="body"):
        return {
            "check": check,
            "title": "Horizontal overflow",
            "severity": "medium",
            "category": "responsive",
            "source": "deterministic",
            "viewport_width": 375,
            "viewport_height": 812,
            "selector": selector,
        }

    def test_persists_finding(self):
        created, skipped = _persist_findings(self.scan, [self._finding()])
        self.assertEqual((created, skipped), (1, 0))
        issue = self.scan.issues.get()
        self.assertEqual(issue.severity, "medium")
        self.assertEqual(issue.source, "deterministic")
        self.assertTrue(issue.dedup_key)

    def test_dedup_skips_duplicate(self):
        created, skipped = _persist_findings(
            self.scan, [self._finding(), self._finding()]
        )
        self.assertEqual((created, skipped), (1, 1))
        self.assertEqual(self.scan.issues.count(), 1)

    def test_different_selector_is_distinct(self):
        created, _ = _persist_findings(
            self.scan, [self._finding(selector="body"), self._finding(selector="header")]
        )
        self.assertEqual(created, 2)

    def test_dedup_key_is_stable(self):
        self.assertEqual(
            _compute_dedup_key(self._finding()),
            _compute_dedup_key(self._finding()),
        )
