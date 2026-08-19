"""Tests for the health API endpoint."""

import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.scans.models import WorkerHeartbeat


class HealthEndpointTests(TestCase):
    def test_health_returns_ok(self):
        response = self.client.get(reverse("api-health"))
        self.assertEqual(response.status_code, 200)

        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "ai-web-doctor")
        self.assertIn("version", payload)
        self.assertIn("scan_mode", payload)
        self.assertIn("build", payload)

    def test_health_reports_worker_liveness_from_heartbeat(self):
        self.client.get(reverse("api-health"))
        payload = json.loads(self.client.get(reverse("api-health")).content)
        self.assertIsNone(payload["worker_last_seen_seconds_ago"])

        WorkerHeartbeat.objects.create(
            pk=1, last_seen=timezone.now(), pid=4242, version="db-poll-2"
        )
        payload = json.loads(self.client.get(reverse("api-health")).content)
        self.assertLessEqual(payload["worker_last_seen_seconds_ago"], 2)
        self.assertEqual(payload["worker_pid"], 4242)
        self.assertEqual(payload["worker_version"], "db-poll-2")
