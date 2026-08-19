"""DB-polling scan worker for deployments without a message broker.

The web process marks scans QUEUED in Postgres; this command (run on a
dedicated worker instance) claims the oldest queued scan and executes it
in-process. It needs no Redis/Celery, so it works on broker-less hosts such
as Render's free tier.
"""

from __future__ import annotations

import logging
import time

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.scans.models import Scan, ScanStatus

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5


class Command(BaseCommand):
    help = "Poll Postgres for queued scans and execute them in-process."

    def handle(self, *args, **options):
        logger.info("scan_worker starting (poll interval %ss)", POLL_INTERVAL_SECONDS)
        while True:
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - the worker must never die
                logger.exception("scan_worker tick failed; continuing")
            time.sleep(POLL_INTERVAL_SECONDS)

    def _tick(self) -> None:
        from apps.scans.services import execute_scan, recover_stale_scans

        recover_stale_scans()
        with transaction.atomic():
            qs = Scan.objects.filter(status=ScanStatus.QUEUED).order_by("created_at")
            if connection.vendor == "postgresql":
                qs = qs.select_for_update(skip_locked=True)
            else:
                qs = qs.select_for_update()  # SQLite: no-op, single worker anyway
            scan = qs.first()
            if scan is None:
                return
            scan.set_running()
        logger.info("scan_worker claimed scan %s", scan.pk)
        try:
            execute_scan(scan.pk)
        except Exception:  # noqa: BLE001 - one bad scan must not kill the worker
            logger.exception("Scan %s crashed in worker; marking failed", scan.pk)
            scan.set_failed(
                "The scan did not complete — the server restarted or ran out of "
                "memory. Please scan again."
            )