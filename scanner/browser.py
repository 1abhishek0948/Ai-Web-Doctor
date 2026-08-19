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

# Flags that keep Chromium's RSS small enough for low-memory hosts: capped V8
# heaps, no background services, no crash reporter. Note: --single-process is
# NOT used — it is unstable in Playwright's bundled Chromium and crashes
# randomly. The V8 heap cap must stay high enough for axe-core + DOM snapshot
# evaluation; 64MB was too low and caused browser crashes.
LOW_MEMORY_ARGS = [
    "--js-flags=--max-old-space-size=128 --max-semi-space-size=2",
    "--renderer-process-limit=1",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--mute-audio",
    "--no-first-run",
    "--disable-default-apps",
    "--disable-component-update",
    "--disable-crash-reporter",
    "--disable-features=Translate,OptimizationHints,MediaRouter,AutofillServerCommunication,CalculateNativeWinOcclusion",
]

BASE_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disk-cache-size=5242880",
]

# Third-party analytics/tracker hosts blocked during scans (speed + privacy).
BLOCKED_HOST_SUBSTRINGS = (
    "google-analytics",
    "googletagmanager",
    "googleadservices",
    "doubleclick",
    "facebook",
    "connect.facebook",
    "analytics.",
    "hotjar",
    "mouseflow",
    "mixpanel",
    "segment.io",
    "amplitude",
    "newrelic",
    "sentry.io",
    "clarity.ms",
)

# Heavy resource URL suffixes blocked via CDP Network.setBlockedURLs. CDP URL
# patterns are glob-style ("*" wildcards), so suffix patterns match any host.
# Note: we deliberately do NOT use context.route() for blocking — the per-
# request async route machinery deadlocks the Playwright driver on pages with
# hundreds of in-flight requests (reproduced on nytimes.com) and adds a
# Python<->Node round-trip for every request.
HEAVY_URL_PATTERNS = (
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.otf",
    "*.eot",
    "*.mp4",
    "*.webm",
    "*.mp3",
    "*.ogg",
    "*.m4a",
    "*.m3u8",
    "*.mov",
)

# Image requests are only blocked in extreme low-memory mode (SCAN_BLOCK_IMAGES).
# Images drive most of Chromium's transient memory on media-heavy sites, but
# removing them makes responsive/overflow measurements slightly less accurate.
BLOCKED_IMAGE_PATTERNS = (
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.avif",
    "*.svg",
    "*.ico",
    "*.bmp",
)


@dataclass(frozen=True)
class BrowserSettings:
    """Tunable browser session settings."""

    headless: bool = True
    viewport: tuple[int, int] = DEFAULT_VIEWPORT
    navigation_timeout_ms: int = 30_000
    network_idle_timeout_ms: int = 2_000
    max_redirects: int = 5
    low_memory: bool = True
    block_service_workers: bool = True
    block_heavy_resources: bool = True
    block_images: bool = False

    def launch_args(self) -> list[str]:
        """Chromium command-line flags for this session."""
        args = list(BASE_ARGS)
        if self.low_memory:
            args.extend(LOW_MEMORY_ARGS)
        return args


def _blocked_url_patterns(settings: BrowserSettings) -> list[str]:
    """CDP URL patterns to block for this session (glob-style, '*' wildcards)."""
    patterns: list[str] = []
    if settings.block_heavy_resources:
        patterns.extend(f"*{host}*" for host in BLOCKED_HOST_SUBSTRINGS)
        patterns.extend(HEAVY_URL_PATTERNS)
    if settings.block_images:
        patterns.extend(BLOCKED_IMAGE_PATTERNS)
    return patterns


def _apply_resource_blocking(context: Any, page: Any, settings: BrowserSettings) -> None:
    """Block heavy/image resources via CDP ``Network.setBlockedURLs``.

    CDP-level blocking is synchronous and imposes zero per-request overhead,
    unlike ``context.route`` which deadlocks the Playwright driver on pages
    with hundreds of concurrent requests.
    """
    patterns = _blocked_url_patterns(settings)
    if not patterns:
        return
    try:
        cdp = context.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.setBlockedURLs", {"urls": patterns})
        context._webdoctor_cdp = cdp  # keep the session alive
    except Exception:  # noqa: BLE001 - blocking is best-effort
        logger.warning("CDP resource blocking unavailable; continuing.", exc_info=True)


class BrowserSession:
    """Context manager that owns a Playwright browser and a single context.

    A single context is shared across viewports so resources (images, CSS, JS)
    are cached between viewport passes — the dominant speed win for
    multi-viewport scans on slow/low-memory hosts.
    """

    def __init__(self, settings: BrowserSettings | None = None) -> None:
        self.settings = settings or BrowserSettings()
        self._playwright: Any = None
        self.browser: Browser | None = None
        self.context: Any = None
        self.page: Page | None = None

    def _launch(self) -> Browser:
        """Launch Chromium, probing for a live page.

        ``--single-process`` (low-memory mode) is occasionally rejected by the
        browser at startup, so if the probe fails we fall back to the stable
        multi-process launch rather than failing the scan.
        """
        try:
            browser = self._playwright.chromium.launch(
                headless=self.settings.headless,
                args=self.settings.launch_args(),
            )
            probe = browser.new_page()
            probe.close()
            return browser
        except Exception as exc:  # noqa: BLE001 - probe crash
            logger.warning(
                "Low-memory Chromium launch failed (%s); retrying with standard flags.",
                str(exc)[:120],
            )
            try:
                if browser.is_connected():
                    browser.close()
            except Exception:  # noqa: BLE001
                pass
            return self._playwright.chromium.launch(
                headless=self.settings.headless,
                args=BASE_ARGS,
            )

    def __enter__(self) -> "BrowserSession":
        self._playwright = sync_playwright().start()
        self.browser = self._launch()
        self.context = self.browser.new_context(
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
            service_workers="block" if self.settings.block_service_workers else "allow",
        )
        self.context.set_default_navigation_timeout(self.settings.navigation_timeout_ms)
        self.context.set_default_timeout(self.settings.navigation_timeout_ms)
        self.page = self.context.new_page()
        _apply_resource_blocking(self.context, self.page, self.settings)
        return self

    def set_viewport(self, viewport: tuple[int, int]) -> Page:
        """Resize the shared page to ``viewport`` and return it."""
        if self.page is None:
            raise RuntimeError("Browser session not started")
        self.page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
        return self.page

    def new_page(self, viewport: tuple[int, int]) -> Page:
        """Open a fresh, isolated page at the given viewport.

        Used by single-page flows (e.g. fix verification) that need a clean
        context; multi-viewport scans reuse the shared page for cache speed.
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
            service_workers="block" if self.settings.block_service_workers else "allow",
        )
        context.set_default_navigation_timeout(self.settings.navigation_timeout_ms)
        context.set_default_timeout(self.settings.navigation_timeout_ms)
        page = context.new_page()
        _apply_resource_blocking(context, page, self.settings)
        return page

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if self.browser is not None:
                try:
                    # Never close() a browser Chromium already died in: the
                    # Node driver throws an unhandled EPIPE that can hang the
                    # whole scan process.
                    if self.browser.is_connected():
                        self.browser.close()
                except Exception:  # noqa: BLE001 - shutdown must never raise
                    logger.debug("Browser already gone during shutdown; ignoring.")
        finally:
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:  # noqa: BLE001 - shutdown must never raise
                    logger.debug("Playwright driver already gone during shutdown.")


def new_browser_session(settings: BrowserSettings | None = None) -> BrowserSession:
    """Convenience factory returning a configured session."""
    return BrowserSession(settings)