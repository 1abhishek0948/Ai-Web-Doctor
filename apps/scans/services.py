"""Scan lifecycle services: persistence, dispatch and execution.

The heavy lifting happens in ``scanner.analyzer``; this module bridges the
scanner to the ORM and decides how scans are executed:

* Production: enqueue a Celery task (Redis broker).
* Development fallback: run the scan in a background daemon thread so the web
  request is never blocked, even without Redis.

The web process never runs the scan synchronously.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Q
from django.utils import timezone

from celery.exceptions import SoftTimeLimitExceeded

from apps.ai.service import analyze_scan
from apps.issues.models import Issue
from apps.scans.models import AIStatus, PageMetric, ProgressStage, Scan, ScanStatus, Screenshot
from apps.scans.scoring import compute_health_score
from config.logging_config import log_event
from scanner.analyzer import ScanError, ScanSecurityError, scan_site
from scanner.browser import BrowserSettings

logger = logging.getLogger(__name__)


def recover_stale_scans() -> int:
    """Mark scans stuck in queued/running as failed.

    A scan can be left permanently ``running`` when the process hosting it
    dies (OOM kill, deploy, crash) — the state machine never gets a chance to
    run its finally handler. This sweeps those scans so the UI shows a clear
    error instead of an eternal spinner.
    """
    cutoff = timezone.now() - timedelta(seconds=settings.MAX_SCAN_DURATION + 60)
    stale = Scan.objects.filter(
        status__in=[ScanStatus.QUEUED, ScanStatus.RUNNING]
    ).filter(Q(started_at__lt=cutoff) | Q(started_at__isnull=True, created_at__lt=cutoff))
    count = stale.count()
    if count:
        logger.warning("Recovering %d stale scan(s) stuck in queued/running.", count)
    for scan in stale.iterator():
        scan.set_failed(
            "The scan did not complete — the server restarted or ran out of memory. "
            "Please scan again."
        )
    if count:
        log_event("scan.recovered", count=count)
    return count


class ScanCreationError(Exception):
    """Raised when a scan cannot be created (e.g. unsafe URL)."""


def create_scan(raw_url: str, *, user=None, client_ip: str | None = None) -> Scan:
    """Create a Scan record for a validated, normalized URL.

    Raises :class:`ScanCreationError` wrapping a user-friendly message when the
    URL is rejected by the security layer.
    """
    from scanner import security

    try:
        validated = security.validate_url(raw_url)
    except security.ScanSecurityError as exc:
        raise ScanCreationError(str(exc)) from exc

    scan = Scan.objects.create(
        url=raw_url,
        normalized_url=validated.url,
        user=user if getattr(user, "is_authenticated", False) else None,
        client_ip=client_ip,
    )
    log_event(
        "scan.created",
        scan_id=scan.pk,
        url=validated.url,
        user=str(getattr(user, "username", "") or ""),
        client_ip=client_ip or "",
    )
    return scan


def _browser_settings() -> BrowserSettings:
    return BrowserSettings(
        headless=settings.PLAYWRIGHT_HEADLESS,
        viewport=tuple(settings.SCAN_VIEWPORTS[0]),
        navigation_timeout_ms=settings.SCAN_PAGE_TIMEOUT_MS,
        network_idle_timeout_ms=settings.SCAN_NETWORK_IDLE_TIMEOUT_MS,
        max_redirects=settings.MAX_REDIRECTS,
    )


def _compute_dedup_key(finding: dict) -> str:
    """Build a stable dedup key for a normalized finding.

    Same check + same viewport + same element = the same root cause, so the
    finding is only persisted once.
    """
    raw = "|".join(
        [
            finding.get("check", ""),
            str(finding.get("viewport_width", "")),
            str(finding.get("viewport_height", "")),
            finding.get("selector", ""),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _persist_findings(scan: Scan, findings: list[dict]) -> tuple[int, int]:
    """Persist deterministic/accessibility findings as Issue rows.

    Returns ``(created, duplicates_skipped)``. Duplicate detection happens via
    ``dedup_key`` which prevents the same root cause being stored twice.
    """
    existing_keys = set(
        scan.issues.values_list("dedup_key", flat=True).exclude(dedup_key="")
    )
    created = 0
    skipped = 0
    for finding in findings:
        key = _compute_dedup_key(finding)
        if key in existing_keys:
            skipped += 1
            continue
        existing_keys.add(key)
        evidence = dict(finding.get("evidence", {}))
        # Persist the check identifier in evidence too: Verify Fix and the
        # scoring service read it from there.
        evidence.setdefault("check", finding.get("check", ""))
        Issue.objects.create(
            scan=scan,
            title=finding.get("title", "UI issue")[:200],
            severity=finding.get("severity", "medium"),
            category=finding.get("category", "responsive"),
            source=finding.get("source", "deterministic"),
            description=finding.get("description", ""),
            selector=finding.get("selector", "")[:500],
            viewport_width=finding.get("viewport_width"),
            viewport_height=finding.get("viewport_height"),
            evidence=evidence,
            confidence=finding.get("confidence", 1.0),
            dedup_key=key,
        )
        created += 1
    return created, skipped


def _compute_health_score(scan: Scan) -> int | None:
    """Derive the 0-100 UI Health score from analyzed categories (scoring)."""
    return compute_health_score(scan)


def execute_scan(scan_id: int) -> None:
    """Run a full scan for the given Scan id and persist its results.

    Never raises: errors are recorded on the Scan so the UI can show a friendly
    message instead of a stack trace.
    """
    scan = Scan.objects.get(pk=scan_id)
    scan.set_running()
    started = time.monotonic()
    log_event("scan.started", scan_id=scan.pk, url=scan.normalized_url or scan.url)

    def over_budget() -> bool:
        """True when the scan has exceeded MAX_SCAN_DURATION."""
        return time.monotonic() - started > settings.MAX_SCAN_DURATION

    try:
        scan.set_progress(ProgressStage.VALIDATING)
        result = scan_site(
            scan.normalized_url or scan.url,
            viewports=settings.SCAN_VIEWPORTS,
            storage=default_storage,
            scan_id=scan.pk,
            settings=_browser_settings(),
            max_response_size=settings.MAX_RESPONSE_SIZE,
        )
    except ScanSecurityError as exc:
        log_event("scan.failed", level=logging.WARNING, scan_id=scan.pk, reason=str(exc), code="security")
        scan.set_failed(str(exc))
        return
    except ScanError as exc:
        log_event("scan.failed", level=logging.WARNING, scan_id=scan.pk, reason=exc.message, code=exc.code)
        scan.set_failed(exc.message)
        return
    except SoftTimeLimitExceeded:
        log_event("scan.failed", scan_id=scan.pk, reason="soft_time_limit", code="timeout")
        scan.set_failed("The scan took too long to complete. Please try again later.")
        return
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.exception("Scan %s crashed unexpectedly", scan.pk)
        log_event("scan.failed", scan_id=scan.pk, reason=str(exc), code="internal")
        scan.set_failed("An unexpected error occurred while scanning this website.")
        return

    successful_viewports = [vp for vp in result.viewport_results if not vp.error]

    # Persist screenshots and metrics per viewport.
    Screenshot.objects.filter(scan=scan).delete()
    PageMetric.objects.filter(scan=scan).delete()
    metric_rows: list[PageMetric] = []
    for vp in result.viewport_results:
        if vp.error:
            continue
        width, height = vp.viewport
        if vp.screenshot_name:
            Screenshot.objects.create(
                scan=scan,
                viewport_width=width,
                viewport_height=height,
                path=vp.screenshot_name,
                file_size=vp.screenshot_bytes or 0,
            )
        for key, value in vp.metrics.items():
            metric_rows.append(
                PageMetric(
                    scan=scan,
                    viewport_width=width,
                    viewport_height=height,
                    key=key,
                    value=str(value),
                )
            )
        overflow_px = max(0, vp.metrics.get("scrollWidth", 0) - width)
        if overflow_px:
            metric_rows.append(
                PageMetric(
                    scan=scan,
                    viewport_width=width,
                    viewport_height=height,
                    key="overflow_px",
                    value=str(overflow_px),
                )
            )
    PageMetric.objects.bulk_create(metric_rows)

    # Persist deterministic + accessibility findings as issues.
    created, _ = _persist_findings(scan, result.findings)
    logger.info("Scan %s persisted %d issues.", scan.pk, created)

    # Archive detailed results (DOM snapshots, findings, warnings) as JSON.
    default_storage.save(
        f"scans/{scan.pk}/result.json",
        ContentFile(
            json.dumps(
                {
                    "final_url": result.final_url,
                    "title": result.title,
                    "status_code": result.status_code,
                    "warnings": result.warnings,
                    "findings": result.findings,
                    "dom_snapshots": [
                        vp.dom_snapshot for vp in result.viewport_results if not vp.error
                    ],
                    "viewports": [
                        list(vp.viewport)
                        for vp in result.viewport_results
                        if not vp.error
                    ],
                }
            ).encode("utf-8")
        ),
    )

    # AI visual analysis (Part 6). Its failure never fails the scan. If the
    # scan has already consumed its time budget, the AI call is skipped so the
    # worker finishes within MAX_SCAN_DURATION.
    scan.set_progress(ProgressStage.AI_ANALYSIS)
    if over_budget():
        scan.ai_status = AIStatus.SKIPPED
        scan.ai_message = (
            "The scan exceeded its time budget, so AI visual analysis was skipped."
        )
        scan.save(update_fields=["ai_status", "ai_message"])
    else:
        scan.ai_status = AIStatus.RUNNING
        scan.save(update_fields=["ai_status"])
        ai_result = analyze_scan(scan)
        scan.ai_status = ai_result.status
        if not ai_result.available and ai_result.message:
            scan.ai_message = ai_result.message
        scan.save(update_fields=["ai_status", "ai_message"])

    scan.set_progress(ProgressStage.REPORTING)
    scan.health_score = _compute_health_score(scan)
    scan.save(update_fields=["health_score"])

    if successful_viewports and len(successful_viewports) < len(result.viewport_results):
        scan.set_partial()
    else:
        scan.set_completed()
    log_event(
        "scan.completed",
        scan_id=scan.pk,
        status=scan.status,
        url=result.final_url,
        health_score=scan.health_score,
        issues=scan.issues.count(),
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def dispatch_scan(scan: Scan) -> None:
    """Dispatch a scan to Celery, or to a dev fallback thread."""
    recover_stale_scans()
    if settings.CELERY_TASK_ALWAYS_EAGER:
        logger.info("Running scan %s in a background thread (dev fallback).", scan.pk)
        log_event("scan.dispatched", scan_id=scan.pk, mode="thread")
        thread = threading.Thread(
            target=execute_scan,
            args=(scan.pk,),
            name=f"scan-{scan.pk}",
            daemon=True,
        )
        thread.start()
        return

    from apps.scans.tasks import run_scan_task

    logger.info("Dispatching scan %s to Celery.", scan.pk)
    log_event("scan.dispatched", scan_id=scan.pk, mode="celery")
    run_scan_task.delay(scan.pk)
