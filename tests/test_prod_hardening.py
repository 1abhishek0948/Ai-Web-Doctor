"""Production-readiness regression tests.

Covers the fixes made for framed-site axe crashes, browser shutdown hangs
after Chromium death, and production-safe scan defaults.
"""

from __future__ import annotations

import unittest
from unittest import mock

from django.test import SimpleTestCase

from scanner import accessibility
from scanner.browser import BrowserSession


class AxeSelectorTests(SimpleTestCase):
    """axe returns nested selector arrays for framed pages; normalization
    must flatten them without crashing (previously a TypeError killed the
    whole viewport on sites like NYTimes)."""

    def test_flat_target_joins_with_spaces(self):
        violation = {
            "id": "color-contrast",
            "impact": "serious",
            "help": "Elements must meet minimum color contrast",
            "helpUrl": "https://example.com/rule",
            "tags": ["wcag2aa"],
            "nodes": [
                {
                    "target": ["#header", ".nav-item"],
                    "html": "<a class=\"nav-item\">x</a>",
                }
            ],
        }
        finding = accessibility._normalize_violation(violation, 390, 844)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["selector"], "#header .nav-item")

    def test_nested_frame_target_flattens_without_crash(self):
        violation = {
            "id": "frame-title",
            "impact": "serious",
            "help": "Frames must have a title",
            "helpUrl": "https://example.com/rule",
            "tags": ["wcag2aa"],
            "nodes": [
                {
                    "target": [["#iframe-chat", ".content"], ["#chatbox"]],
                    "html": "<iframe src=\"chat.html\"></iframe>",
                }
            ],
        }
        finding = accessibility._normalize_violation(violation, 1440, 900)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["selector"], "#iframe-chat .content #chatbox")
        self.assertEqual(finding["evidence"]["node_count"], 1)

    def test_empty_target_falls_back_to_string(self):
        violation = {
            "id": "x",
            "impact": "minor",
            "help": "Some rule",
            "nodes": [{"target": [], "html": "<div></div>"}],
        }
        finding = accessibility._normalize_violation(violation, 375, 812)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["selector"], "")

    def test_flatten_selector_leaf_strings(self):
        self.assertEqual(accessibility._flatten_selector(["#a", ".b"]), "#a .b")
        self.assertEqual(
            accessibility._flatten_selector([["#frame", ".c"], ["#d"]]), "#frame .c #d"
        )
        self.assertEqual(accessibility._flatten_selector(["#a", [".b", ".c"]]), "#a .b .c")
        self.assertEqual(accessibility._flatten_selector(None), "")


class BrowserShutdownTests(SimpleTestCase):
    """BrowserSession.__exit__ must never raise or hang when Chromium died
    mid-scan (previously triggered an EPIPE crash in Playwright's Node
    driver)."""

    def test_exit_with_dead_browser_skips_close(self):
        session = BrowserSession()
        session.browser = mock.Mock()
        session.browser.is_connected.return_value = False
        session._playwright = mock.Mock()

        session.__exit__(None, None, None)  # must not raise

        session.browser.close.assert_not_called()
        session._playwright.stop.assert_called_once()

    def test_exit_swallows_close_error(self):
        session = BrowserSession()
        session.browser = mock.Mock()
        session.browser.is_connected.return_value = True
        session.browser.close.side_effect = RuntimeError("EPIPE")
        session._playwright = mock.Mock()
        session._playwright.stop.side_effect = RuntimeError("driver gone")

        session.__exit__(None, None, None)  # must not raise


class ProductionSettingsTests(SimpleTestCase):
    """Production must force safe scan defaults even when render.yaml env
    vars are missing on the deployment."""

    def test_production_forces_safe_defaults(self):
        # Load production settings in a fresh subprocess to avoid polluting
        # this process's cached settings object. No SCAN_* env vars are set,
        # so concurrency/idle-wait must come from the forced production
        # defaults, and SCAN_SUBPROCESS_MODE must NOT be forced True: scan
        # execution belongs to the dedicated Celery worker instance.
        import subprocess
        import sys

        code = (
            "import os, django\n"
            "os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.production'\n"
            "os.environ['SECRET_KEY'] = 'k' * 60\n"
            "os.environ['ALLOWED_HOSTS'] = 'example.com'\n"
            "os.environ['DATABASE_URL'] = 'postgres://u:p@localhost:5432/db'\n"
            "os.environ.pop('SCAN_SUBPROCESS_MODE', None)\n"
            "os.environ.pop('SCAN_WORKER_MODE', None)\n"
            "os.environ.pop('MAX_CONCURRENT_SCANS', None)\n"
            "os.environ.pop('SCAN_NETWORK_IDLE_TIMEOUT_MS', None)\n"
            "django.setup()\n"
            "from django.conf import settings\n"
            "print(settings.SCAN_WORKER_MODE, settings.SCAN_SUBPROCESS_MODE, "
            "settings.MAX_CONCURRENT_SCANS, settings.SCAN_NETWORK_IDLE_TIMEOUT_MS, "
            "settings.DEBUG, settings.SECURE_HSTS_SECONDS, "
            "settings.SECURE_SSL_REDIRECT)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "False True 1 1500 False 3600 True",
        )

    def test_production_respects_scan_mode_env(self):
        # The blueprint sets SCAN_SUBPROCESS_MODE explicitly; production must
        # respect it instead of hardcoding a mode.
        import subprocess
        import sys

        code = (
            "import os, django\n"
            "os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.production'\n"
            "os.environ['SECRET_KEY'] = 'k' * 60\n"
            "os.environ['ALLOWED_HOSTS'] = 'example.com'\n"
            "os.environ['DATABASE_URL'] = 'postgres://u:p@localhost:5432/db'\n"
            "os.environ['SCAN_SUBPROCESS_MODE'] = 'True'\n"
            "django.setup()\n"
            "from django.conf import settings\n"
            "print(settings.SCAN_SUBPROCESS_MODE)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True")


if __name__ == "__main__":
    unittest.main()
