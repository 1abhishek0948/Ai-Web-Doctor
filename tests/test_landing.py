"""Tests for the public landing page."""

from django.test import TestCase
from django.urls import reverse


class LandingPageTests(TestCase):
    def test_landing_page_renders(self):
        response = self.client.get(reverse("landing"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI Web Doctor")
        self.assertContains(response, "Find broken UI before your users do.")

    def test_landing_page_has_scan_form(self):
        response = self.client.get(reverse("landing"))
        self.assertContains(response, 'id="url"')
        self.assertContains(response, "Scan Website")

    def test_landing_page_labels_example_report_as_example(self):
        response = self.client.get(reverse("landing"))
        self.assertContains(response, "Example report")
        self.assertContains(response, "Sample data for illustration only")
