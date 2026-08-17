"""Celery tasks for website scans."""

from __future__ import annotations

import logging

from celery import shared_task

from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(name="scans.run_scan", bind=True)
def run_scan_task(self, scan_id: int) -> None:
    """Execute a website scan. Errors are recorded on the Scan record."""
    from apps.scans.services import execute_scan

    logger.info("Celery task started for scan %s", scan_id)
    execute_scan(scan_id)


# Hard runtime guard: a scan task is killed if it runs far beyond the allowed
# MAX_SCAN_DURATION. The in-worker deadline (services.execute_scan) also skips
# AI work once the budget is spent, so the hard limit is a last resort.
run_scan_task.soft_time_limit = max(30, settings.MAX_SCAN_DURATION * 2)
run_scan_task.time_limit = max(60, settings.MAX_SCAN_DURATION * 2 + 30)
