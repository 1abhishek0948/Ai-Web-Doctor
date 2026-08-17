"""Verify Fix (Part 8): re-check a single issue against its live website.

The site is loaded again in a real headless browser at the issue's viewport,
the same deterministic checks are re-run, and the before/after measurements are
compared objectively. The AI is never asked whether a measurable problem is
fixed.

Results are persisted as :class:`apps.issues.models.Verification` rows,
including the before/after screenshots for visual comparison.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.issues.models import Issue, Verification, VerificationStatus
from apps.issues.verification import (
    UNVERIFIABLE_MESSAGE,
    build_message,
    classify,
    extract_value,
    find_matching_finding,
    format_value,
    is_known_check,
)
from config.logging_config import log_event
from scanner import accessibility, analyzer, dom, responsive
from scanner import screenshots as screenshot_utils
from scanner.browser import BrowserSession, BrowserSettings

logger = logging.getLogger(__name__)

UNKNOWN_FAILURE_MESSAGE = "Verification could not be completed."


def _browser_settings(width: int, height: int) -> BrowserSettings:
    return BrowserSettings(
        headless=settings.PLAYWRIGHT_HEADLESS,
        viewport=(width, height),
        navigation_timeout_ms=settings.SCAN_PAGE_TIMEOUT_MS,
        network_idle_timeout_ms=settings.SCAN_NETWORK_IDLE_TIMEOUT_MS,
        max_redirects=settings.MAX_REDIRECTS,
    )


def _run_verification_scan(
    url: str,
    width: int,
    height: int,
    *,
    check: str,
) -> tuple[dict[str, int], list[dict[str, Any]], bytes]:
    """Load ``url`` once at one viewport and run the deterministic checks.

    Returns ``(metrics, findings, screenshot_bytes)``. ``findings`` is the full
    set of deterministic findings at that viewport (plus axe findings when the
    issue being verified is an accessibility rule).

    Raises :class:`scanner.analyzer.ScanError` (or any browser error) on
    failure; callers turn that into a failed Verification.
    """
    browser_settings = _browser_settings(width, height)
    with BrowserSession(browser_settings) as session:
        page = session.new_page((width, height))
        analyzer.navigate(page, url, browser_settings, settings.MAX_RESPONSE_SIZE)
        metrics = dom.collect_metrics(page)
        findings = responsive.detect_all(page, metrics)
        if str(check or "").startswith("axe:"):
            findings.extend(
                accessibility.detect_accessibility(
                    page, metrics["innerWidth"], metrics["innerHeight"]
                )
            )
        screenshot_bytes = screenshot_utils.capture_screenshot(page)
    return metrics, findings, screenshot_bytes


def _issue_viewport(issue: Issue) -> tuple[int, int]:
    width = issue.viewport_width or 375
    height = issue.viewport_height or 812
    return int(width), int(height)


def _find_before_screenshot(issue: Issue, width: int, height: int):
    scan = issue.scan
    return (
        scan.screenshots.filter(viewport_width=width, viewport_height=height).first()
        or scan.screenshots.first()
    )


def _persist_screenshots(
    verification: Verification,
    before_path: str | None,
    after_bytes: bytes | None,
    width: int,
    height: int,
) -> None:
    """Copy the before screenshot and store the after screenshot for a verification."""
    prefix = f"verifications/{verification.pk}"
    try:
        if before_path:
            with default_storage.open(before_path, "rb") as handle:
                data = handle.read()
            name = f"{prefix}/before-{width}x{height}.png"
            default_storage.save(name, ContentFile(data))
            verification.screenshot_before = name
        if after_bytes:
            name = f"{prefix}/after-{width}x{height}.png"
            default_storage.save(name, ContentFile(after_bytes))
            verification.screenshot_after = name
    except Exception:  # noqa: BLE001 - screenshots must never fail a verification
        logger.warning("Could not persist verification screenshots for %s", verification.pk)
    verification.save(update_fields=["screenshot_before", "screenshot_after"])


def verify_issue(issue: Issue) -> Verification:
    """Re-check a single issue and persist a :class:`Verification`.

    Never raises: browser or scan failures are recorded on the returned
    Verification so the UI can show a friendly message.
    """
    check = str((issue.evidence or {}).get("check", ""))
    if not is_known_check(check):
        return Verification.objects.create(
            issue=issue,
            status=VerificationStatus.FAILED,
            error_message=UNVERIFIABLE_MESSAGE,
        )

    width, height = _issue_viewport(issue)
    url = issue.scan.normalized_url or issue.scan.url

    try:
        metrics, findings, screenshot_bytes = _run_verification_scan(
            url, width, height, check=check
        )
    except Exception as exc:  # noqa: BLE001 - record friendly failure
        message = exc.message if isinstance(exc, analyzer.ScanError) else UNKNOWN_FAILURE_MESSAGE
        logger.warning("Verification scan failed for issue %s: %s", issue.pk, exc)
        log_event(
            "verification.failed",
            level=logging.WARNING,
            issue_id=issue.pk,
            scan_id=issue.scan_id,
            reason=str(exc)[:300],
        )
        return Verification.objects.create(
            issue=issue,
            status=VerificationStatus.FAILED,
            error_message=message,
        )

    old_value = extract_value(check, issue.evidence, issue.viewport_width)
    matching = find_matching_finding(check, issue.selector, findings)
    if matching is not None:
        new_value = extract_value(check, matching.get("evidence"), metrics["innerWidth"])
    else:
        new_value = 0

    status = classify(old_value, new_value)
    message = build_message(check, status, old_value, new_value)

    verification = Verification.objects.create(
        issue=issue,
        old_value=format_value(check, old_value),
        new_value=format_value(check, new_value),
        status=status,
        message=message,
    )
    _persist_screenshots(
        verification,
        before_path=getattr(_find_before_screenshot(issue, width, height), "path", None),
        after_bytes=screenshot_bytes,
        width=width,
        height=height,
    )
    logger.info(
        "Verified issue %s (%s): %s (%s -> %s)",
        issue.pk, check, status.value, verification.old_value, verification.new_value,
    )
    log_event(
        "verification.completed",
        issue_id=issue.pk,
        scan_id=issue.scan_id,
        check=check,
        status=status.value,
        old_value=verification.old_value,
        new_value=verification.new_value,
    )
    return verification
