"""Playwright browser session management.

The scanner runs Chromium headlessly through Playwright's synchronous API,
which is safe to use inside a Celery worker (or a background thread in the
development fallback) because neither runs an asyncio event loop.

Resource limits are applied per session:

* per-navigation timeout
* maximum redirects

Response-size enforcement and redirect-host validation live in ``analyzer.py``
where the actual response objects are inspected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright

logger = logging.getLogger(__name__)

DEFAULT_VIEWPORT = (375, 812)


@dataclass(frozen=True)
class BrowserSettings:
    """Tunable browser session settings."""

    headless: bool = True
    viewport: tuple[int, int] = DEFAULT_VIEWPORT
    navigation_timeout_ms: int = 30_000
    network_idle_timeout_ms: int = 10_000
    max_redirects: int = 5


class BrowserSession:
    """Context manager that owns a Playwright browser and a single page."""

    def __init__(self, settings: BrowserSettings | None = None) -> None:
        self.settings = settings or BrowserSettings()
        self._playwright: Any = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    def __enter__(self) -> "BrowserSession":
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(
            headless=self.settings.headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
            ],
        )
        context = self.browser.new_context(
            viewport={
                "width": self.settings.viewport[0],
                "height": self.settings.viewport[1],
            },
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            locale="en-US",
        )
        context.set_default_navigation_timeout(self.settings.navigation_timeout_ms)
        context.set_default_timeout(self.settings.navigation_timeout_ms)
        self.page = context.new_page()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if self.browser is not None:
                self.browser.close()
        finally:
            if self._playwright is not None:
                self._playwright.stop()

    def new_page(self, viewport: tuple[int, int]) -> Page:
        """Open a fresh page in its own context at the given viewport.

        Used by multi-viewport scanning so each viewport gets an isolated,
        clean page (separate localStorage, cookies and viewport).
        """
        if self.browser is None:
            raise RuntimeError("Browser session not started")
        context = self.browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            locale="en-US",
        )
        context.set_default_navigation_timeout(self.settings.navigation_timeout_ms)
        context.set_default_timeout(self.settings.navigation_timeout_ms)
        return context.new_page()


def new_browser_session(settings: BrowserSettings | None = None) -> BrowserSession:
    """Convenience factory returning a configured session."""
    return BrowserSession(settings)
