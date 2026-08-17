"""SEO tests: robots.txt, sitemap.xml, meta tags, noindex rules, JSON-LD."""

from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.issues.models import Issue
from apps.scans.models import Scan, ScanStatus

SITE_URL = "https://aiwebdoctor.onrender.com"


@override_settings(SITE_URL=SITE_URL)
class RobotsAndSitemapTests(TestCase):
    def test_robots_txt(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        content = response.content.decode()
        self.assertIn("User-agent: *", content)
        self.assertIn("Disallow: /admin/", content)
        self.assertIn("Disallow: /accounts/", content)
        self.assertIn("Disallow: /api/", content)
        self.assertIn("Disallow: /scans/", content)
        self.assertIn(f"Sitemap: {SITE_URL}/sitemap.xml", content)

    def test_sitemap_xml(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")
        content = response.content.decode()
        self.assertIn(f"<loc>{SITE_URL}/</loc>", content)
        self.assertIn("<changefreq>weekly</changefreq>", content)
        self.assertIn("<priority>1.0</priority>", content)


@override_settings(SITE_URL=SITE_URL)
class LandingMetaTests(TestCase):
    def test_landing_meta_tags(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("<title>", html)
        self.assertIn('name="description"', html)
        self.assertIn(f'<link rel="canonical" href="http://testserver/">', html)
        self.assertIn('name="robots" content="index, follow"', html)
        self.assertIn('property="og:title"', html)
        self.assertIn('property="og:description"', html)
        self.assertIn('property="og:url"', html)
        self.assertIn(f'property="og:image" content="{SITE_URL}/static/img/og-image.png"', html)
        self.assertIn('name="twitter:card" content="summary_large_image"', html)
        self.assertIn("favicon.svg", html)
        self.assertIn("apple-touch-icon", html)

    def test_landing_json_ld(self):
        response = self.client.get("/")
        html = response.content.decode()
        self.assertIn('id="site-json"', html)
        self.assertIn('"@type": "WebSite"', html)
        self.assertIn('"@type": "Organization"', html)
        self.assertIn('"@type": "SoftwareApplication"', html)
        self.assertIn('id="faq-json"', html)
        self.assertIn('"@type": "FAQPage"', html)
        self.assertIn("How is AI used in the analysis?", html)
        self.assertIn(f'"{SITE_URL}/"', html)

    def test_canonical_strips_query_string(self):
        response = self.client.get("/?utm_source=test&utm_medium=email")
        html = response.content.decode()
        self.assertIn('<link rel="canonical" href="http://testserver/">', html)
        self.assertNotIn("utm_source", html.split('rel="canonical"')[1].split('">')[0])


class NoIndexTests(TestCase):
    def test_scan_results_noindex(self):
        scan = Scan.objects.create(
            url="https://example.com/",
            normalized_url="example.com",
            status=ScanStatus.COMPLETED,
            health_score=88,
        )
        response = self.client.get(reverse("scans:scan-results", args=[scan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Robots-Tag"], "noindex, follow")
        self.assertIn('name="robots" content="noindex, follow"', response.content.decode())

    def test_auth_pages_noindex_nofollow(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertIn('name="robots" content="noindex, nofollow"', response.content.decode())

    def test_404_noindex(self):
        response = self.client.get("/this-page-does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertIn('name="robots" content="noindex, follow"', response.content.decode())

    def test_results_breadcrumb_json_ld(self):
        scan = Scan.objects.create(
            url="https://example.com/",
            normalized_url="example.com",
            status=ScanStatus.COMPLETED,
            health_score=88,
        )
        response = self.client.get(reverse("scans:scan-results", args=[scan.pk]))
        html = response.content.decode()
        self.assertIn('"@type": "BreadcrumbList"', html)
        self.assertIn(f'"{SITE_URL}/scans/{scan.pk}/results/"', html)


@override_settings(SITE_URL=SITE_URL)
class IssuePageJsonLdTests(TestCase):
    def test_issue_detail_breadcrumb(self):
        scan = Scan.objects.create(
            url="https://example.com/",
            normalized_url="example.com",
            status=ScanStatus.COMPLETED,
            health_score=88,
        )
        issue = Issue.objects.create(
            scan=scan,
            title="Text clipped at 375px",
            severity="medium",
            category="layout",
            evidence={"check": "text_overflow", "clipped_px": 12},
        )
        response = self.client.get(reverse("scans:issue-detail", args=[scan.pk, issue.pk]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('"@type": "BreadcrumbList"', html)
        self.assertIn(f'"{SITE_URL}/scans/{scan.pk}/issues/{issue.pk}/"', html)
        self.assertEqual(response["X-Robots-Tag"], "noindex, follow")