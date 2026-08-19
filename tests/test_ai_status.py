"""Tests for machine-readable AI analysis status tracking.

The dashboard distinguishes "analyzed with no issues" from "analysis never
happened" through ``Scan.ai_status``. These tests pin the statuses produced by
``analyze_scan``/``execute_scan`` (unavailable, failed, rate_limited,
completed) and the banner rendered by the results view.
"""

from __future__ import annotations

import json
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.ai.providers import AIProviderError
from apps.ai import service
from apps.ai.service import AIAnalysisResult
from apps.scans.models import AIStatus, Scan, ScanStatus
from apps.scans import services as scan_services
from scanner.analyzer import SiteScanResult, ViewportScanResult

VALID_ISSUE = {
    "title": "Header overlaps content",
    "severity": "high",
    "category": "layout",
    "viewport_width": 375,
    "viewport_height": 812,
    "description": "The sticky header covers the first section on mobile.",
    "likely_cause": "The header uses a fixed height without reserving space.",
    "recommendation": "Add top padding equal to the header height on small screens.",
    "confidence": 0.85,
}


class RaisingProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, error: Exception) -> None:
        self.error = error

    def is_available(self) -> bool:
        return True

    def analyze_ui(self, payload: dict) -> str:
        raise self.error


class AnalyzeScanStatusTests(TestCase):
    def setUp(self) -> None:
        self.scan = Scan.objects.create(
            url="https://example.com",
            normalized_url="https://example.com/",
            status=ScanStatus.COMPLETED,
        )
        self.payload = {"prompt": "context", "images": [{"viewport": (375, 812)}]}

    def _run(self, provider=None):
        with mock.patch.object(service, "get_provider", return_value=provider), (
            mock.patch.object(service, "build_payload", return_value=self.payload)
        ):
            return service.analyze_scan(self.scan)

    def test_disabled_or_no_key_is_unavailable(self):
        with mock.patch.object(service, "_provider_available", return_value=False):
            result = service.analyze_scan(self.scan)
        self.assertFalse(result.available)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason, "disabled_or_no_key")

    def test_analysis_runs_without_screenshots(self):
        class OkProvider(RaisingProvider):
            def analyze_ui(self, payload: dict) -> str:
                return json.dumps({"issues": []})

        with mock.patch.object(service, "_provider_available", return_value=True), (
            mock.patch.object(service, "get_provider", return_value=OkProvider(RuntimeError("unused")))
        ), mock.patch.object(service, "build_payload", return_value={"prompt": "x", "images": []}):
            result = service.analyze_scan(self.scan)
        self.assertTrue(result.available)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.reason, "ok")

    def test_rate_limited_on_429(self):
        result = self._run(RaisingProvider(AIProviderError("Gemini returned HTTP 429: quota exceeded")))
        self.assertFalse(result.available)
        self.assertEqual(result.status, "rate_limited")
        self.assertEqual(result.reason, "provider_rate_limited")
        self.assertIn("rate-limited", result.message)

    def test_failed_on_provider_error(self):
        result = self._run(RaisingProvider(AIProviderError("connection reset")))
        self.assertFalse(result.available)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "provider_or_validation_error")

    def test_completed_on_valid_response(self):
        class OkProvider(RaisingProvider):
            def analyze_ui(self, payload: dict) -> str:
                return json.dumps({"issues": [VALID_ISSUE]})

        result = self._run(OkProvider(RuntimeError("unused")))
        self.assertTrue(result.available)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.reason, "ok")


class ExecuteScanStatusTests(TestCase):
    def setUp(self) -> None:
        self.scan = Scan.objects.create(
            url="https://example.com",
            normalized_url="https://example.com/",
            status=ScanStatus.QUEUED,
        )

    def _site_result(self, findings=None) -> SiteScanResult:
        return SiteScanResult(
            url="https://example.com/",
            final_url="https://example.com/",
            title="Example",
            status_code=200,
            viewport_results=[
                ViewportScanResult(
                    viewport=(375, 812),
                    metrics={"innerWidth": 375, "innerHeight": 812},
                )
            ],
            findings=findings or [],
            warnings=[],
        )

    def _run(self, ai_result: AIAnalysisResult, findings=None) -> None:
        class FakeStorage:
            def save(self, name, content):
                return name

        with mock.patch.object(
            scan_services, "scan_site", return_value=self._site_result(findings)
        ), mock.patch.object(
            scan_services, "analyze_scan", return_value=ai_result
        ), mock.patch.object(scan_services, "default_storage", FakeStorage()):
            scan_services.execute_scan(self.scan.pk)

    def test_persists_unavailable_status(self):
        result = AIAnalysisResult(
            available=False,
            status="unavailable",
            reason="disabled_or_no_key",
            message="AI visual analysis unavailable.",
        )
        self._run(result)
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.ai_status, AIStatus.UNAVAILABLE)
        self.assertEqual(self.scan.ai_message, "AI visual analysis unavailable.")
        self.assertEqual(self.scan.status, ScanStatus.COMPLETED)
        self.assertEqual(self.scan.health_score, 100)

    def test_persists_rate_limited_status(self):
        result = AIAnalysisResult(
            available=False,
            status="rate_limited",
            reason="provider_rate_limited",
            message="The AI provider is rate-limited (quota exceeded).",
        )
        self._run(result)
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.ai_status, AIStatus.RATE_LIMITED)
        self.assertEqual(self.scan.health_score, 100)

    def test_persists_completed_status(self):
        result = AIAnalysisResult(
            available=True, created=1, combined=0, status="completed", reason="ok"
        )
        self._run(result)
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.ai_status, AIStatus.COMPLETED)
        self.assertEqual(self.scan.health_score, 100)

    def test_persists_check_in_evidence(self):
        finding = {
            "check": "horizontal_overflow",
            "category": "responsive",
            "title": "Horizontal overflow at 375px",
            "severity": "high",
            "viewport_width": 375,
            "viewport_height": 812,
            "description": "Document is wider than the viewport.",
            "evidence": {"overflow_px": 42},
            "confidence": 1.0,
            "source": "deterministic",
        }
        result = AIAnalysisResult(
            available=False, status="unavailable", reason="disabled_or_no_key"
        )
        self._run(result, findings=[finding])
        self.scan.refresh_from_db()
        issue = self.scan.issues.get()
        self.assertEqual(issue.evidence.get("check"), "horizontal_overflow")


class ResultsViewStatusTests(TestCase):
    def setUp(self) -> None:
        self.scan = Scan.objects.create(
            url="https://example.com",
            normalized_url="https://example.com/",
            status=ScanStatus.COMPLETED,
            ai_status=AIStatus.RATE_LIMITED,
            ai_message="The AI provider is rate-limited (quota exceeded). "
            "Check your Gemini API plan/billing and try again later.",
        )

    def test_failure_banner_hidden(self):
        response = self.client.get(reverse("scans:scan-results", args=[self.scan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "AI visual analysis")
        self.assertNotContains(response, "quota")

    def test_unavailable_banner_hidden(self):
        self.scan.ai_status = AIStatus.UNAVAILABLE
        self.scan.ai_message = "AI visual analysis unavailable."
        self.scan.save(update_fields=["ai_status", "ai_message"])
        response = self.client.get(reverse("scans:scan-results", args=[self.scan.pk]))
        self.assertNotContains(response, "AI visual analysis")
        self.assertNotContains(response, "Unavailable")

    def test_renders_no_score_for_failed_scan(self):
        self.scan.status = ScanStatus.FAILED
        self.scan.save(update_fields=["status"])
        response = self.client.get(reverse("scans:scan-results", args=[self.scan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no score to show")