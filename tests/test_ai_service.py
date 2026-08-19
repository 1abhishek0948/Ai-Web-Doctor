"""Tests for the AI service: Part 6 visual analysis and Part 7 fix generation.

The Gemini provider is always mocked. These tests exercise the validation,
retry, dedup, and fallback behavior without any network access.
"""

from __future__ import annotations

import json
from unittest import mock

from django.test import TestCase, override_settings

from apps.ai import service
from apps.ai.providers import AIProviderError
from apps.ai.schemas import normalize_language
from apps.issues.models import Issue, IssueSource
from apps.scans.models import Scan, ScanStatus

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

VALID_FIX = {
    "explanation": "The header needs to reserve space for its fixed height.",
    "recommended_change": "Add top padding to the page body on mobile.",
    "code": "body { padding-top: 56px; }",
    "language": "css",
}


class FakeProvider:
    """Stand-in provider with a scripted list of raw responses."""

    name = "fake"
    model = "fake-model"

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def is_available(self) -> bool:
        return True

    def _next(self) -> str:
        if not self.responses:
            raise AIProviderError("no more scripted responses")
        if len(self.responses) == 1:
            return self.responses[0]
        return self.responses.pop(0)

    def analyze_ui(self, payload: dict) -> str:
        self.calls.append("analyze_ui")
        return self._next()

    def generate_fix(self, payload: dict) -> str:
        self.calls.append("generate_fix")
        return self._next()


class AIAnalysisTests(TestCase):
    def setUp(self) -> None:
        self.scan = Scan.objects.create(
            url="https://example.com",
            normalized_url="https://example.com/",
            status=ScanStatus.COMPLETED,
        )
        self.payload = {"prompt": "context", "images": [{"viewport": (375, 812)}]}

    def _run(self, responses: list[str]):
        provider = FakeProvider(responses)
        with mock.patch.object(service, "get_provider", return_value=provider), (
            mock.patch.object(service, "build_payload", return_value=self.payload)
        ):
            result = service.analyze_scan(self.scan)
        return provider, result

    def test_valid_analysis_creates_issue(self):
        provider, result = self._run([json.dumps({"issues": [VALID_ISSUE]})])
        self.assertTrue(result.available)
        self.assertEqual(result.created, 1)
        self.assertEqual(self.scan.issues.count(), 1)
        issue = self.scan.issues.get()
        self.assertEqual(issue.source, IssueSource.AI)
        self.assertEqual(issue.severity, "high")
        self.assertEqual(issue.confidence, 0.85)
        self.assertEqual(provider.calls, ["analyze_ui"])

    def test_malformed_json_unavailable(self):
        _, result = self._run(["this is not json"])
        self.assertFalse(result.available)
        self.assertEqual(self.scan.issues.count(), 0)

    def test_missing_description_issue_skipped(self):
        bad = dict(VALID_ISSUE)
        del bad["description"]
        _, result = self._run([json.dumps({"issues": [bad]})])
        self.assertTrue(result.available)
        self.assertEqual(result.created, 0)
        self.assertEqual(self.scan.issues.count(), 0)

    def test_invalid_severity_falls_back_to_info(self):
        bad = dict(VALID_ISSUE, severity="catastrophic")
        _, result = self._run([json.dumps({"issues": [bad]})])
        self.assertTrue(result.available)
        self.assertEqual(result.created, 1)
        self.assertEqual(self.scan.issues.get().severity, "info")

    def test_invalid_category_falls_back_to_ux(self):
        bad = dict(VALID_ISSUE, category="wizardry")
        _, result = self._run([json.dumps({"issues": [bad]})])
        self.assertTrue(result.available)
        self.assertEqual(result.created, 1)
        self.assertEqual(self.scan.issues.get().category, "ux")

    def test_string_viewport_coerced(self):
        bad = dict(VALID_ISSUE, viewport_width="375px", viewport_height="812px")
        _, result = self._run([json.dumps({"issues": [bad]})])
        self.assertTrue(result.available)
        issue = self.scan.issues.get()
        self.assertEqual(issue.viewport_width, 375)
        self.assertEqual(issue.viewport_height, 812)

    def test_extra_fields_ignored(self):
        bad = dict(VALID_ISSUE, extra_field="whatever", type="visual")
        _, result = self._run([json.dumps({"issues": [bad]})])
        self.assertTrue(result.available)
        self.assertEqual(result.created, 1)

    def test_mixed_valid_and_invalid_issues(self):
        bad = dict(VALID_ISSUE)
        del bad["confidence"]
        payload = json.dumps({"issues": [VALID_ISSUE, bad, VALID_ISSUE]})
        _, result = self._run([payload])
        self.assertTrue(result.available)
        self.assertEqual(result.created, 1)
        self.assertEqual(self.scan.issues.count(), 1)

    def test_json_with_nested_braces_parsed(self):
        raw = (
            "Here is the analysis:\n```json\n"
            '{"issues": [{"title": "Nested braces {in text}", '
            '"severity": "low", "category": "ux", "viewport_width": 375, '
            '"viewport_height": 812, "description": "Some description text.", '
            '"likely_cause": "A cause.", "recommendation": "A fix.", '
            '"confidence": 0.5}]}\n```'
        )
        _, result = self._run([raw])
        self.assertTrue(result.available)
        self.assertEqual(result.created, 1)
        self.assertEqual(self.scan.issues.get().title, "Nested braces {in text}")

    def test_provider_error_unavailable(self):
        provider = FakeProvider([])

        def boom(payload):
            raise AIProviderError("timed out")

        provider.analyze_ui = boom
        with mock.patch.object(service, "get_provider", return_value=provider), (
            mock.patch.object(service, "build_payload", return_value=self.payload)
        ):
            result = service.analyze_scan(self.scan)
        self.assertFalse(result.available)
        self.assertEqual(self.scan.issues.count(), 0)

    def test_retry_once_then_success(self):
        _, result = self._run(
            ["not json", json.dumps({"issues": [VALID_ISSUE]})]
        )
        self.assertTrue(result.available)
        self.assertEqual(result.created, 1)

    def test_unavailable_message_preserved(self):
        _, result = self._run(["not json"])
        self.assertEqual(result.message, service.AI_UNAVAILABLE_MESSAGE)

    def test_ai_disabled(self):
        provider = FakeProvider([])
        with mock.patch.object(service, "get_provider", return_value=provider), (
            mock.patch.object(service, "build_payload", return_value=self.payload)
        ), override_settings(AI_ENABLED=False):
            result = service.analyze_scan(self.scan)
        self.assertFalse(result.available)
        self.assertEqual(result.message, service.AI_UNAVAILABLE_MESSAGE)
        self.assertEqual(provider.calls, [])

    def test_analysis_runs_without_screenshots(self):
        provider = FakeProvider([json.dumps({"issues": [VALID_ISSUE]})])
        with mock.patch.object(service, "get_provider", return_value=provider), (
            mock.patch.object(service, "build_payload", return_value={"prompt": "x", "images": []})
        ):
            result = service.analyze_scan(self.scan)
        self.assertTrue(result.available)
        self.assertEqual(result.created, 1)
        self.assertEqual(provider.calls, ["analyze_ui"])

    def test_text_only_payload_by_default(self):
        from apps.ai.providers.gemini import GeminiProvider

        provider = GeminiProvider(api_key="AIza-test-key-xyz")
        payload = {"prompt": "hello", "images": [{"mime_type": "image/jpeg", "data": "AAAA"}]}
        with mock.patch.object(provider, "_request", return_value='{"issues": []}') as request:
            provider.analyze_ui(payload)
        body = request.call_args[0][0]
        self.assertEqual(len(body["contents"][0]["parts"]), 1)
        self.assertNotIn("inline_data", body["contents"][0]["parts"][0])

    def test_images_included_when_enabled(self):
        from apps.ai.providers.gemini import GeminiProvider

        provider = GeminiProvider(api_key="AIza-test-key-xyz")
        payload = {"prompt": "hello", "images": [{"mime_type": "image/jpeg", "data": "AAAA"}]}
        with mock.patch.object(provider, "_request", return_value='{"issues": []}') as request, (
            override_settings(AI_SEND_IMAGES=True)
        ):
            provider.analyze_ui(payload)
        body = request.call_args[0][0]
        self.assertEqual(len(body["contents"][0]["parts"]), 2)
        self.assertIn("inline_data", body["contents"][0]["parts"][1])

    def test_prompt_truncated_to_token_budget(self):
        long_finding = dict(
            VALID_ISSUE,
            title="X" * 200,
            description="Y" * 1000,
            likely_cause="Z" * 600,
            recommendation="W" * 600,
        )
        Issue.objects.create(
            scan=self.scan,
            title=long_finding["title"],
            severity="high",
            category="layout",
            source=IssueSource.DETERMINISTIC,
            description=long_finding["description"],
        )
        with override_settings(AI_MAX_PROMPT_TOKENS=100):
            payload = service.build_payload(self.scan)
        self.assertLessEqual(len(payload["prompt"]), 512 + 64)
        self.assertIn("truncated to token budget", payload["prompt"])

    def test_ai_finding_combines_with_deterministic(self):
        existing = Issue.objects.create(
            scan=self.scan,
            title="Sticky header overlaps content on mobile",
            severity="medium",
            category="layout",
            source=IssueSource.DETERMINISTIC,
            viewport_width=375,
            viewport_height=812,
            description="The sticky header covers the first section at 375px wide.",
        )
        _, result = self._run([json.dumps({"issues": [VALID_ISSUE]})])
        self.assertEqual(result.combined, 1)
        self.assertEqual(result.created, 0)
        self.assertEqual(self.scan.issues.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.source, IssueSource.COMBINED)
        self.assertIn("Recommended:", existing.ai_explanation)

    def test_ai_issue_dedup_within_response(self):
        payload = json.dumps({"issues": [VALID_ISSUE, VALID_ISSUE]})
        _, result = self._run([payload])
        self.assertEqual(result.created, 1)


class FixGenerationTests(TestCase):
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
            source=IssueSource.DETERMINISTIC,
            viewport_width=375,
            viewport_height=812,
            description="The sticky header covers the first section on mobile.",
        )

    def _run(self, responses: list[str]):
        provider = FakeProvider(responses)
        with mock.patch.object(service, "get_provider", return_value=provider), (
            mock.patch.object(service, "_build_fix_payload", return_value={"prompt": "x", "images": [], "issue": self.issue})
        ):
            result = service.generate_fix(self.issue)
        return provider, result

    def test_successful_fix(self):
        provider, result = self._run([json.dumps(VALID_FIX)])
        self.assertTrue(result.ok)
        self.assertEqual(result.code, "body { padding-top: 56px; }")
        self.assertEqual(result.language, "css")
        self.assertIn("header", result.explanation)
        self.assertEqual(provider.calls, ["generate_fix"])

    def test_malformed_fix(self):
        _, result = self._run(["not json"])
        self.assertFalse(result.ok)
        self.assertIn("JSON", result.error)

    def test_api_failure(self):
        provider = FakeProvider([])

        def boom(payload):
            raise AIProviderError("unreachable")

        provider.generate_fix = boom
        with mock.patch.object(service, "get_provider", return_value=provider), (
            mock.patch.object(service, "_build_fix_payload", return_value={"prompt": "x", "images": [], "issue": self.issue})
        ):
            result = service.generate_fix(self.issue)
        self.assertFalse(result.ok)
        self.assertIn("could not be reached", result.error)

    def test_unsupported_language(self):
        fix = dict(VALID_FIX, language="python")
        _, result = self._run([json.dumps(fix)])
        self.assertFalse(result.ok)
        self.assertIn("unsupported language", result.error)
        self.assertIn("CSS", result.error)

    def test_empty_response(self):
        fix = dict(VALID_FIX, code="   ")
        _, result = self._run([json.dumps(fix)])
        self.assertFalse(result.ok)
        self.assertIn("empty fix", result.error)

    def test_language_alias_normalized(self):
        fix = dict(VALID_FIX, language="js")
        _, result = self._run([json.dumps(fix)])
        self.assertTrue(result.ok)
        self.assertEqual(result.language, "javascript")

    def test_ai_disabled_returns_unavailable(self):
        with mock.patch.object(service, "_provider_available", return_value=False):
            result = service.generate_fix(self.issue)
        self.assertFalse(result.ok)
        self.assertIn("unavailable", result.error)


class SchemaHelpersTests(TestCase):
    def test_normalize_language_known(self):
        self.assertEqual(normalize_language("css"), "css")
        self.assertEqual(normalize_language("CSS3"), "css")
        self.assertEqual(normalize_language("html"), "html")
        self.assertEqual(normalize_language("markup"), "html")
        self.assertEqual(normalize_language("javascript"), "javascript")
        self.assertEqual(normalize_language("js"), "javascript")
        self.assertEqual(normalize_language("React"), "jsx")
        self.assertEqual(normalize_language("JSX"), "jsx")

    def test_normalize_language_unknown(self):
        self.assertIsNone(normalize_language("python"))
        self.assertIsNone(normalize_language(""))
