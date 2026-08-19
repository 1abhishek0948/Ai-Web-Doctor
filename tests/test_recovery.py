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