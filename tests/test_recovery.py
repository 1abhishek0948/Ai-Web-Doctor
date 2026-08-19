"""Tests for stale-scan recovery (process death / OOM safety net)."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.scans.models import Scan, ScanStatus
from apps.scans.services import recover_stale_scans

OLD = timezone.now() - timedelta(hours=1)


def _scan(status: str, **kwargs) -> Scan:
    kwargs.setdefault("url", "https://example.com/")
    kwargs.setdefault("normalized_url", "https://example.com/")
    kwargs.setdefault("status", status)
    if status == ScanStatus.RUNNING:
        kwargs.setdefault("started_at", OLD)
    return Scan.objects.create(**kwargs)


@override_settings(MAX_SCAN_DURATION=120)
class RecoverStaleScansTests(TestCase):
    def test_recovery_marks_stuck_running_scan_failed(self):
        scan = _scan(ScanStatus.RUNNING)
        self.assertEqual(recover_stale_scans(), 1)
        scan.refresh_from_db()
        self.assertEqual(scan.status, ScanStatus.FAILED)
        self.assertIn("did not complete", scan.error_message)

    def test_recovery_marks_old_queued_scan_failed(self):
        scan = Scan.objects.create(
            url="https://example.com/",
            status=ScanStatus.QUEUED,
        )
        Scan.objects.filter(pk=scan.pk).update(created_at=OLD)
        self.assertEqual(recover_stale_scans(), 1)
        scan.refresh_from_db()
        self.assertEqual(scan.status, ScanStatus.FAILED)
        self.assertIn("never picked up", scan.error_message)

    def test_fresh_running_scan_is_untouched(self):
        scan = _scan(ScanStatus.RUNNING, started_at=timezone.now())
        self.assertEqual(recover_stale_scans(), 0)
        scan.refresh_from_db()
        self.assertEqual(scan.status, ScanStatus.RUNNING)

    def test_completed_and_failed_scans_are_untouched(self):
        completed = _scan(ScanStatus.COMPLETED)
        failed = _scan(ScanStatus.FAILED)
        self.assertEqual(recover_stale_scans(), 0)
        self.assertEqual(Scan.objects.get(pk=completed.pk).status, ScanStatus.COMPLETED)
        self.assertEqual(Scan.objects.get(pk=failed.pk).status, ScanStatus.FAILED)

    def test_dispatch_recovers_stale_scans(self):
        stale = _scan(ScanStatus.RUNNING)
        scan = _scan(ScanStatus.QUEUED)
        from apps.scans import services

        with mock.patch.object(services, "execute_scan"):
            services.dispatch_scan(scan)
        stale.refresh_from_db()
        self.assertEqual(stale.status, ScanStatus.FAILED)

    def test_scan_list_view_recovers_stale(self):
        _scan(ScanStatus.RUNNING)
        response = self.client.get(reverse("scans:scan-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Scan.objects.get().status, ScanStatus.FAILED)

    def test_results_view_recovers_stale(self):
        scan = _scan(ScanStatus.RUNNING)
        response = self.client.get(reverse("scans:scan-results", args=[scan.pk]))
        self.assertEqual(response.status_code, 200)
        scan.refresh_from_db()
        self.assertEqual(scan.status, ScanStatus.FAILED)

    def test_stale_queued_scan_does_not_block_new_scan(self):
        # A queued scan abandoned by a dead worker/OOM occupies the concurrency
        # slot; submitting a new scan must sweep it first, not say "busy".
        stale = Scan.objects.create(
            url="https://old.example.com/",
            status=ScanStatus.QUEUED,
        )
        Scan.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(hours=1))
        with mock.patch("scanner.security._resolve_hostname", return_value=["93.184.216.34"]), (
            override_settings(MAX_CONCURRENT_SCANS=1)
        ), mock.patch("apps.scans.views.dispatch_scan"):
            response = self.client.post(
                reverse("scans:scan-list"), {"url": "https://example.com"}, follow=True
            )
        stale.refresh_from_db()
        self.assertEqual(stale.status, ScanStatus.FAILED)
        self.assertEqual(Scan.objects.filter(status=ScanStatus.QUEUED).count(), 1)
        self.assertNotContains(response, "in progress")

    def test_dispatch_in_worker_mode_keeps_scan_queued(self):
        # The web process only marks scans QUEUED; the dedicated worker claims
        # them from Postgres. No thread, subprocess or broker involved.
        scan = _scan(ScanStatus.QUEUED)
        from apps.scans import services

        with (
            override_settings(SCAN_WORKER_MODE=True),
            mock.patch.object(services, "execute_scan") as execute,
            mock.patch.object(services, "_dispatch_subprocess") as sub,
        ):
            services.dispatch_scan(scan)
        scan.refresh_from_db()
        self.assertEqual(scan.status, ScanStatus.QUEUED)
        execute.assert_not_called()
        sub.assert_not_called()


class ScanWorkerCommandTests(TestCase):
    """The DB-polling worker claims queued scans and executes them."""

    def test_worker_claims_oldest_queued_scan(self):
        from apps.scans.management.commands.scan_worker import Command
        from apps.scans import services

        older = _scan(ScanStatus.QUEUED)
        newer = _scan(ScanStatus.QUEUED)
        Scan.objects.filter(pk=newer.pk).update(
            created_at=timezone.now() + timedelta(seconds=5)
        )
        with mock.patch.object(services, "execute_scan") as execute, mock.patch.object(
            services, "recover_stale_scans"
        ):
            Command()._tick()
        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertEqual(older.status, ScanStatus.RUNNING)
        self.assertEqual(newer.status, ScanStatus.QUEUED)
        execute.assert_called_once_with(older.pk)

    def test_worker_skips_when_nothing_queued(self):
        from apps.scans.management.commands.scan_worker import Command
        from apps.scans import services

        with mock.patch.object(services, "execute_scan") as execute:
            Command()._tick()
        execute.assert_not_called()

    def test_worker_writes_heartbeat_every_tick(self):
        from apps.scans.management.commands.scan_worker import Command
        from apps.scans import services
        from apps.scans.models import WorkerHeartbeat

        with mock.patch.object(services, "execute_scan"), mock.patch.object(
            services, "recover_stale_scans"
        ):
            Command()._tick()
        heartbeat = WorkerHeartbeat.objects.get(pk=1)
        self.assertIsNotNone(heartbeat.last_seen)
        self.assertGreater(heartbeat.pid, 0)
        self.assertEqual(heartbeat.version, "db-poll-2")

    def test_worker_marks_execution_errors_failed(self):
        from apps.scans.management.commands.scan_worker import Command
        from apps.scans import services

        scan = _scan(ScanStatus.QUEUED)
        with mock.patch.object(
            services, "execute_scan", side_effect=RuntimeError("boom")
        ), mock.patch.object(services, "recover_stale_scans"):
            Command()._tick()
        scan.refresh_from_db()
        self.assertEqual(scan.status, ScanStatus.FAILED)
        self.assertIn("worker", scan.error_message)


class ScanWorkerWatchdogTests(TestCase):
    """The worker's hard watchdog must be armed for every claimed scan."""

    def test_watchdog_armed_and_cancelled_after_scan(self):
        from apps.scans.management.commands.scan_worker import Command
        from apps.scans import services

        with mock.patch("threading.Timer") as timer_cls:
            timer_cls.return_value.cancel = mock.Mock()
            Command()._start_watchdog()
        deadline_s = timer_cls.call_args[0][0]
        self.assertGreaterEqual(deadline_s, 600)
        timer_cls.return_value.daemon = True


class BrowserMemorySettingsTests(TestCase):
    """Low-memory browser settings stay inside the free-tier budget."""

    def test_low_memory_launch_args_cap_v8_heap(self):
        from scanner.browser import BrowserSettings

        args = BrowserSettings(low_memory=True, v8_heap_mb=192).launch_args()
        self.assertIn("--js-flags=--max-old-space-size=192 --max-semi-space-size=4", args)

    def test_axe_runs_on_desktop_viewport_only_in_low_memory_mode(self):
        from scanner.analyzer import _should_run_axe
        from scanner.browser import BrowserSettings

        low = BrowserSettings(low_memory=True, axe_viewports="desktop")
        self.assertFalse(_should_run_axe(0, 2, low))
        self.assertTrue(_should_run_axe(1, 2, low))

    def test_axe_runs_everywhere_when_configured(self):
        from scanner.analyzer import _should_run_axe
        from scanner.browser import BrowserSettings

        all_vp = BrowserSettings(low_memory=True, axe_viewports="all")
        self.assertTrue(_should_run_axe(0, 2, all_vp))
        self.assertTrue(_should_run_axe(1, 2, all_vp))