"""Orchestrates a real browser scan of a URL.

``scan_url`` scans a single URL at a single viewport (kept for unit tests and
backwards compatibility). ``scan_site`` scans a URL at multiple viewports,
running deterministic responsive checks and axe-core accessibility checks at
every viewport, and returns a plain :class:`SiteScanResult`.

The analyzer is deliberately independent of Django models and views. It takes a
URL (and optional storage), does the real browser work, and returns plain
dataclasses. Persisting results to the database is the caller's job
(``apps/scans/services.py``).

Every step has a friendly error message so the UI never shows a stack trace.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Error as PlaywrightError

from scanner.browser import BrowserSession, BrowserSettings
from scanner import accessibility, dom, responsive, screenshots, security
from config.logging_config import log_event

logger = logging.getLogger(__name__)


class ScanError(Exception):
    """Base error raised when a scan cannot complete.

    ``message`` is a human-friendly explanation suitable for end users.
    """

    def __init__(self, message: str, *, code: str = "scan_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class ScanTimeoutError(ScanError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="timeout")


class ScanSecurityError(ScanError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="security")


class ScanNavigationError(ScanError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="navigation")


@dataclass
class ScanResult:
    """Plain result of a single-viewport scan, independent of any ORM model."""

    url: str
    final_url: str
    title: str
    status_code: int | None
    viewport: tuple[int, int]
    metrics: dict[str, int] = field(default_factory=dict)
    dom_snapshot: list[dict[str, Any]] = field(default_factory=list)
    overflow: dict[str, Any] | None = None
    elements_outside: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    screenshot_name: str | None = None
    screenshot_bytes: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class ViewportScanResult:
    """Results gathered for a single viewport of a multi-viewport scan."""

    viewport: tuple[int, int]
    metrics: dict[str, int] = field(default_factory=dict)
    dom_snapshot: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    screenshot_name: str | None = None
    screenshot_bytes: int = 0
    final_url: str = ""
    title: str = ""
    status_code: int | None = None
    error: str | None = None


@dataclass
class SiteScanResult:
    """Plain aggregate result of a multi-viewport scan."""

    url: str
    final_url: str
    title: str
    status_code: int | None
    viewport_results: list[ViewportScanResult] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _friendly_playwright_error(exc: Exception) -> ScanError:
    if isinstance(exc, PlaywrightTimeoutError):
        return ScanTimeoutError("The website took too long to load.")
    text = str(exc).lower()
    if "net::err_name_not_resolved" in text or "dns" in text:
        return ScanNavigationError("The website's address could not be resolved.")
    if "net::err_connection_refused" in text:
        return ScanNavigationError("The website refused the connection.")
    if "net::err_connection_timed_out" in text or "timed out" in text:
        return ScanTimeoutError("The website took too long to load.")
    if "ssl" in text or "certificate" in text:
        return ScanNavigationError("The website has an invalid SSL certificate.")
    return ScanError("The website could not be loaded.")


def _validate_redirect_chain(request: Any, max_redirects: int) -> None:
    """Walk Playwright's redirect chain and validate every hop's host."""
    current = request
    hops: list[Any] = []
    while current is not None:
        hops.append(current)
        current = current.redirected_from
    redirects = max(0, len(hops) - 1)
    if redirects > max_redirects:
        raise ScanNavigationError(
            f"The website redirected more than {max_redirects} times."
        )
    for hop in reversed(hops):
        url = hop.url
        if not url:
            continue
        try:
            security.validate_redirect_url(url)
        except security.ScanSecurityError as exc:
            raise ScanSecurityError(str(exc)) from exc


def _check_response_size(response: Any, max_size: int) -> None:
    headers = {k.lower(): v for k, v in (response.headers or {}).items()}
    content_length = headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_size:
        raise ScanNavigationError(
            f"The website's page exceeds the maximum allowed size "
            f"({max_size} bytes)."
        )


def _navigate(page: Any, target_url: str, settings: BrowserSettings, max_size: int):
    """Navigate ``page`` to ``target_url`` with size + redirect-host checks.

    Returns ``(response, final_url, status_code)``.
    """
    captured_request: list[Any] = []

    def on_request(request: Any) -> None:
        captured_request.append(request)

    page.on("request", on_request)
    response = None
    try:
        response = page.goto(
            target_url,
            wait_until="domcontentloaded",
            timeout=settings.navigation_timeout_ms,
        )
    except PlaywrightError as exc:
        log_event(
            "scan.playwright_error",
            level=logging.WARNING,
            url=target_url,
            reason=str(exc)[:300],
        )
        raise _friendly_playwright_error(exc) from exc

    if response is not None:
        _check_response_size(response, max_size)

    if captured_request:
        try:
            _validate_redirect_chain(captured_request[-1], settings.max_redirects)
        except security.ScanSecurityError as exc:
            raise ScanSecurityError(str(exc)) from exc

    try:
        page.wait_for_load_state("networkidle", timeout=settings.network_idle_timeout_ms)
    except PlaywrightTimeoutError:
        logger.info("networkidle never reached for %s; continuing anyway", target_url)

    status_code = response.status if response is not None else None
    return response, page.url, status_code


def _scan_page(
    page: Any,
    target_url: str,
    viewport: tuple[int, int],
    settings: BrowserSettings,
    storage: Any | None,
    scan_id: int | str | None,
    max_response_size: int,
    *,
    run_accessibility: bool = True,
) -> ViewportScanResult:
    """Navigate and measure a page at one viewport, returning a viewport result.

    Never raises for per-viewport problems: failures are recorded on the result
    so the overall scan can continue and report partial results.
    """
    width, height = viewport
    result = ViewportScanResult(viewport=viewport)
    try:
        _, final_url, status_code = _navigate(page, target_url, settings, max_response_size)
        page_info = dom.collect_page_info(page)
        metrics = dom.collect_metrics(page)
        result.metrics = metrics
        result.dom_snapshot = dom.collect_dom_snapshot(page)
        result.final_url = final_url
        result.title = page_info.get("title") or final_url
        result.status_code = status_code

        result.findings.extend(responsive.detect_all(page, metrics))

        if run_accessibility:
            result.findings.extend(
                accessibility.detect_accessibility(page, metrics["innerWidth"], metrics["innerHeight"])
            )

        screenshot_bytes = screenshots.capture_screenshot(page)
        result.screenshot_bytes = len(screenshot_bytes)
        if storage is not None:
            result.screenshot_name = screenshots.save_screenshot(
                storage,
                screenshot_bytes,
                scan_id=scan_id if scan_id is not None else "pending",
                viewport_width=metrics["innerWidth"],
                viewport_height=metrics["innerHeight"],
            )
    except ScanError as exc:
        result.error = exc.message
    except Exception as exc:  # noqa: BLE001 - per-viewport guard
        logger.warning("Viewport %s failed: %s", viewport, exc)
        log_event(
            "scan.viewport_error",
            level=logging.WARNING,
            url=target_url,
            viewport=f"{viewport[0]}x{viewport[1]}",
            reason=str(exc)[:300],
        )
        result.error = _friendly_playwright_error(exc).message
    return result


def navigate(page: Any, target_url: str, settings: BrowserSettings, max_response_size: int):
    """Public wrapper around :func:`_navigate` for other modules (e.g. verification).

    Returns ``(response, final_url, status_code)`` and raises :class:`ScanError`
    subclasses with user-friendly messages on failure.
    """
    return _navigate(page, target_url, settings, max_response_size)


def scan_url(
    url: str,
    *,
    storage: Any | None = None,
    scan_id: int | str | None = None,
    settings: BrowserSettings | None = None,
    max_response_size: int = 5 * 1024 * 1024,
) -> ScanResult:
    """Scan a single URL at a single viewport. Returns a :class:`ScanResult`.

    Raises :class:`ScanError` subclasses with user-friendly messages.
    """
    try:
        validated = security.validate_url(url)
    except security.ScanSecurityError as exc:
        raise ScanSecurityError(str(exc)) from exc

    target_url = validated.url
    browser_settings = settings or BrowserSettings()

    with BrowserSession(browser_settings) as session:
        page = session.page
        assert page is not None

        vp = _scan_page(
            page,
            target_url,
            browser_settings.viewport,
            browser_settings,
            storage,
            scan_id,
            max_response_size,
            run_accessibility=False,
        )
        if vp.error:
            raise ScanError(vp.error)

    metrics = vp.metrics
    final_url = vp.final_url or target_url
    title = vp.title or target_url
    status_code = vp.status_code
    findings = vp.findings
    overflow = None
    elements_outside = []
    for finding in findings:
        if finding["check"] == "horizontal_overflow":
            overflow = finding
        elif finding["check"] == "element_outside_viewport":
            elements_outside.append(finding)

    return ScanResult(
        url=target_url,
        final_url=final_url,
        title=title,
        status_code=status_code,
        viewport=browser_settings.viewport,
        metrics=metrics,
        dom_snapshot=vp.dom_snapshot,
        overflow=overflow,
        elements_outside=elements_outside,
        findings=findings,
        screenshot_name=vp.screenshot_name,
        screenshot_bytes=vp.screenshot_bytes,
    )


def scan_site(
    url: str,
    *,
    viewports: list[tuple[int, int]] | None = None,
    storage: Any | None = None,
    scan_id: int | str | None = None,
    settings: BrowserSettings | None = None,
    max_response_size: int = 5 * 1024 * 1024,
) -> SiteScanResult:
    """Scan a URL at multiple viewports. Returns a :class:`SiteScanResult`.

    Raises :class:`ScanSecurityError` only when the initial URL is rejected.
    Per-viewport failures produce partial results instead of failing the scan.
    """
    try:
        validated = security.validate_url(url)
    except security.ScanSecurityError as exc:
        raise ScanSecurityError(str(exc)) from exc

    target_url = validated.url
    browser_settings = settings or BrowserSettings()
    viewport_list = list(viewports or [])

    with BrowserSession(browser_settings) as session:
        first_page = session.page
        assert first_page is not None

        viewport_results: list[ViewportScanResult] = []
        for index, viewport in enumerate(viewport_list):
            if index == 0:
                page = first_page
                session.settings = BrowserSettings(**{**browser_settings.__dict__, "viewport": viewport})
                viewport_results.append(
                    _scan_page(
                        page,
                        target_url,
                        viewport,
                        browser_settings,
                        storage,
                        scan_id,
                        max_response_size,
                    )
                )
            else:
                page = session.new_page(viewport)
                viewport_results.append(
                    _scan_page(
                        page,
                        target_url,
                        viewport,
                        browser_settings,
                        storage,
                        scan_id,
                        max_response_size,
                    )
                )

    successful = [vp for vp in viewport_results if not vp.error]
    if not successful:
        first_error = viewport_results[0].error or "The website could not be loaded."
        raise ScanError(first_error)

    first = successful[0]
    findings: list[dict[str, Any]] = []
    for vp in viewport_results:
        findings.extend(vp.findings)

    warnings = [
        f"Viewport {vp.viewport[0]}x{vp.viewport[1]} could not be scanned: {vp.error}"
        for vp in viewport_results
        if vp.error
    ]

    return SiteScanResult(
        url=target_url,
        final_url=first.final_url or target_url,
        title=first.title or target_url,
        status_code=first.status_code,
        viewport_results=viewport_results,
        findings=findings,
        warnings=warnings,
    )
