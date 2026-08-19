"""DB-polling scan worker for deployments without a message broker.

The web process marks scans QUEUED in Postgres; this command (run on a
dedicated worker instance) claims the oldest queued scan and executes it
in-process. It needs no Redis/Celery, so it works on broker-less hosts such
as Render's free tier.

Resilience:
- A heartbeat row is written every poll tick so the health endpoint can report
  whether the worker is alive (and the DB write keeps the free-tier worker
  busy enough not to idle out).
- A hard watchdog thread kills the whole worker if a scan exceeds its deadline.
  Playwright sync calls can hang forever when a renderer wedges under memory
  pressure; no in-process timeout can interrupt them, so ``os._exit`` from a
  daemon thread is the only guarantee. The platform restarts the worker and the
  stale-scan sweeper marks the orphaned scan failed.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from apps.scans.models import Scan, ScanStatus, WorkerHeartbeat

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5
HEARTBEAT_INTERVAL_SECONDS = 5
WORKER_VERSION = "db-poll-2"


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

    def _heartbeat(self) -> None:
        WorkerHeartbeat.objects.update_or_create(
            pk=1,
            defaults={
                "last_seen": timezone.now(),
                "pid": os.getpid(),
                "version": WORKER_VERSION,
            },
        )

    def _tick(self) -> None:
        from apps.scans.services import execute_scan, recover_stale_scans

        self._heartbeat()
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

        watchdog = self._start_watchdog()
        try:
            execute_scan(scan.pk)
        except Exception:  # noqa: BLE001 - one bad scan must not kill the worker
            logger.exception("Scan %s crashed in worker; marking failed", scan.pk)
            scan.set_failed(
                "The scan failed on the worker before completing. Please scan again."
            )
        finally:
            watchdog.cancel()

    @staticmethod
    def _start_watchdog() -> threading.Timer:
        """Kill the worker if a scan exceeds its hard deadline.

        Aligned with the stale-sweep RUNNING window (``MAX_SCAN_DURATION*2+60``)
        plus a small buffer, so a legitimately slow scan is never killed while a
        wedged one always is. ``os._exit`` skips Django teardown, which is
        exactly what we want for a wedged process.
        """
        deadline_s = max(settings.MAX_SCAN_DURATION * 2 + 60 + 60, 600)
        timer = threading.Timer(deadline_s, os._exit, args=(1,))
        timer.daemon = True
        timer.start()
        return timer