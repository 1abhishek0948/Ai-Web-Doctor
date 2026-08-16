"""Tests for Part 8 Verify Fix: pure verification logic, the verify_issue
service (with the browser mocked), and the issue-verify view.
"""

from __future__ import annotations

from io import BytesIO
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.issues import verification as v
from apps.issues.models import (
    Issue,
    IssueSource,
    Verification,
    VerificationStatus,
)
from apps.issues import services
from apps.scans import views
from apps.scans.models import Scan, ScanStatus, Screenshot
from scanner import analyzer


class VerificationLogicTests(TestCase):
    def test_extract_value_numeric(self):
        self.assertEqual(
            v.extract_value("horizontal_overflow", {"overflow_px": 42}, 375), 42
        )
        self.assertIsNone(v.extract_value("horizontal_overflow", {"overflow_px": "big"}, 375))
        self.assertIsNone(v.extract_value("horizontal_overflow", {}, 375))

    def test_extract_value_binary_and_axe(self):
        self.assertEqual(v.extract_value("broken_image", {}, 375), 1)
        self.assertEqual(v.extract_value("axe:image-alt", {}, 375), 1)

    def test_extract_value_element_outside_viewport(self):
        evidence = {"element": {"box": {"x": 0, "width": 400}}}
        self.assertEqual(v.extract_value("element_outside_viewport", evidence, 375), 25)
        self.assertIsNone(v.extract_value("element_outside_viewport", {}, 375))

    def test_format_value(self):
        self.assertEqual(v.format_value("horizontal_overflow", 42), "42px")
        self.assertEqual(v.format_value("horizontal_overflow", None), "—")
        self.assertEqual(v.format_value("broken_image", 1), "present")
        self.assertEqual(v.format_value("broken_image", 0), "absent")
        self.assertEqual(v.format_value("axe:image-alt", 0), "absent")

    def test_classify(self):
        self.assertEqual(v.classify(42, 0), VerificationStatus.VERIFIED)
        self.assertEqual(v.classify(42, None), VerificationStatus.VERIFIED)
        self.assertEqual(v.classify(None, 0), VerificationStatus.VERIFIED)
        self.assertEqual(v.classify(42, 8), VerificationStatus.IMPROVED)
        self.assertEqual(v.classify(42, 42), VerificationStatus.FAILED)
        self.assertEqual(v.classify(42, 60), VerificationStatus.FAILED)
        self.assertEqual(v.classify(None, 5), VerificationStatus.FAILED)

    def test_find_matching_finding_prefers_exact_selector(self):
        findings = [
            {"check": "horizontal_overflow", "selector": ".header", "evidence": {"overflow_px": 8}},
            {"check": "horizontal_overflow", "selector": ".banner", "evidence": {"overflow_px": 12}},
        ]
        found = v.find_matching_finding("horizontal_overflow", ".banner", findings)
        self.assertEqual(found["evidence"]["overflow_px"], 12)
        self.assertIsNone(v.find_matching_finding("horizontal_overflow", ".nope", []))

    def test_find_matching_falls_back_to_selectorless(self):
        findings = [{"check": "text_overflow", "selector": "", "evidence": {"clipped_px": 5}}]
        found = v.find_matching_finding("text_overflow", "span.x", findings)
        self.assertEqual(found["evidence"]["clipped_px"], 5)

    def test_build_message(self):
        self.assertIn(
            "no longer detected",
            v.build_message("horizontal_overflow", VerificationStatus.VERIFIED, 42, 0),
        )
        self.assertIn(
            "improved",
            v.build_message("horizontal_overflow", VerificationStatus.IMPROVED, 42, 8),
        )
        self.assertIn(
            "still detected",
            v.build_message("horizontal_overflow", VerificationStatus.FAILED, 42, 42),
        )

    def test_known_checks(self):
        self.assertTrue(v.is_known_check("horizontal_overflow"))
        self.assertTrue(v.is_known_check("broken_image"))
        self.assertTrue(v.is_known_check("axe:image-alt"))
        self.assertFalse(v.is_known_check("not_a_check"))
        self.assertTrue(v.is_axe_check("axe:color-contrast"))
        self.assertFalse(v.is_axe_check("horizontal_overflow"))


class FakeStorage:
    """In-memory stand-in for the file storage backend."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.saved: list[str] = []

    def open(self, name: str, mode: str = "rb"):  # noqa: ARG002
        return BytesIO(self.files.get(name, b"before-screenshot-bytes"))

    def save(self, name: str, content) -> str:
        data = content.read()
        self.files[name] = data
        self.saved.append(name)
        return name


class VerifyIssueServiceTests(TestCase):
    def setUp(self) -> None:
        self.scan = Scan.objects.create(
            url="https://example.com",
            normalized_url="https://example.com/",
            status=ScanStatus.COMPLETED,
        )
        self.issue = Issue.objects.create(
            scan=self.scan,
            title="Horizontal overflow",
            severity="medium",
            category="responsive",
            source=IssueSource.DETERMINISTIC,
            selector=".banner",
            viewport_width=375,
            viewport_height=812,
            evidence={"check": "horizontal_overflow", "overflow_px": 42},
        )

    def _run(self, return_value=None, side_effect=None) -> Verification:
        with mock.patch.object(
            services, "_run_verification_scan", return_value=return_value, side_effect=side_effect
        ), mock.patch.object(services, "_persist_screenshots", return_value=None):
            return services.verify_issue(self.issue)

    def _finding(self, overflow_px: int | None = None, selector: str | None = None) -> dict:
        finding = {"check": "horizontal_overflow", "selector": selector or self.issue.selector}
        if overflow_px is not None:
            finding["evidence"] = {"overflow_px": overflow_px}
        return finding

    def test_verified_when_finding_gone(self):
        verification = self._run(return_value=({"innerWidth": 375}, [], b"after"))
        self.assertEqual(verification.status, VerificationStatus.VERIFIED)
        self.assertEqual(verification.old_value, "42px")
        self.assertEqual(verification.new_value, "0px")
        self.assertIn("no longer detected", verification.message)

    def test_improved_when_reduced(self):
        verification = self._run(return_value=({"innerWidth": 375}, [self._finding(8)], b"after"))
        self.assertEqual(verification.status, VerificationStatus.IMPROVED)
        self.assertEqual(verification.new_value, "8px")
        self.assertIn("improved", verification.message)

    def test_failed_when_unchanged(self):
        verification = self._run(return_value=({"innerWidth": 375}, [self._finding(42)], b"after"))
        self.assertEqual(verification.status, VerificationStatus.FAILED)
        self.assertEqual(verification.new_value, "42px")
        self.assertIn("still detected", verification.message)

    def test_failed_when_worse(self):
        verification = self._run(return_value=({"innerWidth": 375}, [self._finding(60)], b"after"))
        self.assertEqual(verification.status, VerificationStatus.FAILED)
        self.assertEqual(verification.new_value, "60px")

    def test_scan_error_records_message(self):
        verification = self._run(side_effect=analyzer.ScanError("site unreachable"))
        self.assertEqual(verification.status, VerificationStatus.FAILED)
        self.assertEqual(verification.error_message, "site unreachable")

    def test_unexpected_error_generic_message(self):
        verification = self._run(side_effect=RuntimeError("boom"))
        self.assertEqual(verification.status, VerificationStatus.FAILED)
        self.assertEqual(verification.error_message, services.UNKNOWN_FAILURE_MESSAGE)

    def test_unverifiable_check_skips_scan(self):
        self.issue.evidence = {"check": "not_a_check"}
        self.issue.save(update_fields=["evidence"])
        with mock.patch.object(services, "_run_verification_scan") as scan:
            verification = self._run()
        self.assertEqual(verification.status, VerificationStatus.FAILED)
        self.assertEqual(verification.error_message, v.UNVERIFIABLE_MESSAGE)
        scan.assert_not_called()

    def test_binary_check_verified(self):
        self.issue.evidence = {"check": "broken_image"}
        self.issue.save(update_fields=["evidence"])
        verification = self._run(return_value=({"innerWidth": 375}, [], b"after"))
        self.assertEqual(verification.status, VerificationStatus.VERIFIED)
        self.assertEqual(verification.old_value, "present")
        self.assertEqual(verification.new_value, "absent")

    def test_axe_check_runs_scan(self):
        self.issue.evidence = {"check": "axe:image-alt"}
        self.issue.save(update_fields=["evidence"])
        verification = self._run(return_value=({"innerWidth": 375}, [], b"after"))
        self.assertEqual(verification.status, VerificationStatus.VERIFIED)
        self.assertEqual(verification.old_value, "present")

    def test_persists_database_row(self):
        verification = self._run(return_value=({"innerWidth": 375}, [self._finding(8)], b"after"))
        self.assertEqual(self.issue.verifications.count(), 1)
        self.assertEqual(
            Verification.objects.get(pk=verification.pk).issue_id, self.issue.pk
        )
        self.assertEqual(verification.status, VerificationStatus.IMPROVED)

    def test_persists_before_after_screenshots(self):
        Screenshot.objects.create(
            scan=self.scan,
            viewport_width=375,
            viewport_height=812,
            path="scans/1/viewport-375x812.png",
        )
        storage = FakeStorage()
        with mock.patch.object(
            services, "_run_verification_scan", return_value=({"innerWidth": 375}, [], b"after-bytes")
        ), mock.patch.object(services, "default_storage", storage):
            verification = services.verify_issue(self.issue)
        self.assertTrue(verification.has_screenshots)
        self.assertTrue(verification.screenshot_before.endswith("before-375x812.png"))
        self.assertTrue(verification.screenshot_after.endswith("after-375x812.png"))
        self.assertIn(verification.screenshot_after, storage.saved)
        self.assertEqual(storage.files[verification.screenshot_after], b"after-bytes")


class VerifyIssueViewTests(TestCase):
    def setUp(self) -> None:
        self.scan = Scan.objects.create(
            url="https://example.com",
            normalized_url="https://example.com/",
            status=ScanStatus.COMPLETED,
        )
        self.issue = Issue.objects.create(
            scan=self.scan,
            title="Horizontal overflow",
            severity="medium",
            category="responsive",
            source=IssueSource.DETERMINISTIC,
            evidence={"check": "horizontal_overflow", "overflow_px": 42},
        )
        self.url = reverse("scans:issue-verify", args=[self.scan.pk, self.issue.pk])

    def test_post_renders_partial(self):
        verification = Verification.objects.create(
            issue=self.issue,
            status=VerificationStatus.VERIFIED,
            old_value="42px",
            new_value="0px",
        )
        with mock.patch.object(views, "verify_issue", return_value=verification):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/verify_result.html")
        self.assertEqual(response.context["verification"].status, VerificationStatus.VERIFIED)

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_missing_issue_404(self):
        response = self.client.post(
            reverse("scans:issue-verify", args=[self.scan.pk, 9999])
        )
        self.assertEqual(response.status_code, 404)
