"""Sitemap and robots.txt views."""

from __future__ import annotations

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.http import HttpResponse
from django.template import loader
from django.urls import reverse


class StaticViewSitemap(Sitemap):
    """Public, indexable pages. Scan reports are noindexed and excluded."""

    priority = 1.0
    changefreq = "weekly"

    def items(self):
        return ["landing"]

    def location(self, item):
        return reverse(item)


def sitemap_xml(request):
    """Render sitemap.xml using SITE_URL for absolute URLs."""
    site_map = StaticViewSitemap()
    site_map.request = request
    base = settings.SITE_URL.rstrip("/")
    urls = [
        {
            "location": f"{base}{site_map.location(item)}",
            "changefreq": site_map.changefreq,
            "priority": str(site_map.priority),
        }
        for item in site_map.items()
    ]
    xml = loader.render_to_string("sitemap.xml", {"urlset": urls}, request=request)
    return HttpResponse(xml, content_type="application/xml")


def robots_txt(request):
    """Render robots.txt with the absolute sitemap URL."""
    base = settings.SITE_URL.rstrip("/")
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /accounts/",
        "Disallow: /api/",
        "Disallow: /scans/",
        "",
        f"Sitemap: {base}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")