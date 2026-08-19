"""Tests for Part 9 production hardening: rate limiting, resource limits,
friendly error pages, AI payload size capping and structured logging.
"""

from __future__ import annotations

import json
import logging
from unittest import mock

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings
from django.template.loader import get_template
from django.urls import reverse

from apps.ai import service as ai_service
from apps.ai.providers.gemini import GeminiProvider
from apps.scans.models import Scan
from config import logging_config


def _fake_storage():
    class Storage:
        def __init__(self):
            self.files = {}
            self.saved = []

        def save(self, name, content):
            self.files[name] = content.read()
            self.saved.append(name)
            return name

    return Storage()


class ScanRateLimitTests(TestCase):
    def setUp(self) -> None:
        self.url = reverse("scans:scan-list")
        patcher = mock.patch("apps.scans.views.dispatch_scan")
        self.addCleanup(patcher.stop)
        patcher.start()
        resolver = mock.patch(
            "scanner.security._resolve_hostname", return_value=["93.184.216.34"]
        )
        self.addCleanup(resolver.stop)
        resolver.start()

    def _post(self, url="https://example.com"):
        return self.client.post(self.url, {"url": url})

    def test_anonymous_quota(self):
        with override_settings(
            RATE_LIMIT_ANONYMOUS_SCANS_PER_DAY=2, MAX_CONCURRENT_SCANS=100
        ):
            for _ in range(2):
                self.assertEqual(self._post().status_code, 302)
            response = self._post()
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "scan limit", status_code=429)
        self.assertEqual(Scan.objects.count(), 2)

    def test_authenticated_quota(self):
        user = User.objects.create_user("alice", password="pw")
        self.client.force_login(user)
        with override_settings(
            RATE_LIMIT_AUTHED_SCANS_PER_DAY=2, MAX_CONCURRENT_SCANS=100
        ):
            for _ in range(2):
                self.assertEqual(self._post().status_code, 302)
            response = self._post()
        self.assertEqual(response.status_code, 429)

    def test_quota_resets_between_anonymous_and_authenticated(self):
        user = User.objects.create_user("bob", password="pw")
        with override_settings(
            RATE_LIMIT_ANONYMOUS_SCANS_PER_DAY=1,
            RATE_LIMIT_AUTHED_SCANS_PER_DAY=1,
            MAX_CONCURRENT_SCANS=100,
        ):
            self.assertEqual(self._post().status_code, 302)
            self.assertEqual(self._post().status_code, 429)
            self.client.force_login(user)
            # A different caller (authenticated) has its own quota.
            self.assertEqual(self._post().status_code, 302)

    def test_concurrency_limit_blocks_extra_queues(self):
        with override_settings(MAX_CONCURRENT_SCANS=0):
            response = self.client.post(self.url, {"url": "https://example.com"}, follow=True)
        self.assertContains(response, "busy")
        self.assertEqual(Scan.objects.count(), 0)


class ScreenshotSizeTests(TestCase):
    def test_saves_within_limit(self):
        from scanner import screenshots

        storage = _fake_storage()
        name = screenshots.save_screenshot(
            storage, b"x" * 100, scan_id=1, viewport_width=320, viewport_height=800, max_bytes=1000
        )
        self.assertEqual(name, "scans/1/viewport-320x800.jpg")
        self.assertEqual(storage.saved, [name])

    def test_drops_uncompressible_oversized(self):
        from scanner import screenshots

        storage = _fake_storage()
        name = screenshots.save_screenshot(
            storage,
            b"not-a-real-png" * 2000,
            scan_id=1,
            viewport_width=320,
            viewport_height=800,
            max_bytes=1000,
        )
        self.assertEqual(name, "")
        self.assertEqual(storage.saved, [])


class AiPayloadSizeTests(TestCase):
    def test_fit_drops_largest_images(self):
        images = [
            {"data": "a" * 3000, "viewport": (1440, 900)},
            {"data": "b" * 500, "viewport": (768, 1024)},
            {"data": "c" * 100, "viewport": (375, 812)},
        ]
        with override_settings(MAX_AI_REQUEST_SIZE=2000):
            kept = ai_service._fit_payload_size("x" * 10, images)
        self.assertEqual(len(kept), 2)
        self.assertTrue(all(len(img["data"]) <= 500 for img in kept))

    def test_prompt_over_limit_returns_empty(self):
        with override_settings(MAX_AI_REQUEST_SIZE=50):
            kept = ai_service._fit_payload_size("y" * 500, [{"data": "z"}])
        self.assertEqual(kept, [])


class ErrorPageTests(TestCase):
    def test_404_uses_friendly_page(self):
        response = self.client.get("/definitely-not-a-page/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Page not found", status_code=404)

    def test_500_does_not_leak_traceback(self):
        from django.views.defaults import server_error

        request = RequestFactory().get("/")
        request.user = mock.Mock(is_authenticated=False)
        with override_settings(DEBUG=False):
            response = server_error(request)
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Something went wrong", status_code=500)
        self.assertNotContains(response, "Traceback", status_code=500)

    def test_429_template_renders_with_limit(self):
        template = get_template("429.html")
        html = template.render(
            {"limit": 3, "used": 3, "is_authenticated": False}, RequestFactory().get("/")
        )
        self.assertIn("3 scans per day", html)


class StructuredLoggingTests(TestCase):
    def test_json_formatter_emits_valid_json_with_extra(self):
        formatter = logging_config.JsonFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "scan.created", None, None
        )
        record.extra_fields = {"scan_id": 7}
        parsed = json.loads(formatter.format(record))
        self.assertEqual(parsed["message"], "scan.created")
        self.assertEqual(parsed["scan_id"], 7)
        self.assertEqual(parsed["level"], "INFO")

    def test_log_event_does_not_raise(self):
        with self.assertLogs("aiwebdoctor.events", level="INFO") as captured:
            logging_config.log_event("verification.completed", issue_id=1, status="verified")
        self.assertIn("verification.completed", "".join(captured.output))


class GeminiApiKeyTests(TestCase):
    def test_api_key_in_header_not_url(self):
        provider = GeminiProvider(api_key="super-secret-key-xyz")
        with mock.patch("httpx.post") as post:
            post.return_value = mock.Mock(
                status_code=200,
                json=lambda: {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]},
            )
            provider._request({"contents": []})
        call = post.call_args
        self.assertEqual(call.kwargs["headers"]["x-goog-api-key"], "super-secret-key-xyz")
        self.assertNotIn("key=", call.args[0])
