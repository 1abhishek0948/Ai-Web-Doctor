"""Template context processors for SEO-related values."""

from __future__ import annotations

from django.conf import settings

from apps.seo.seo_data import SEO_FAQS


def seo(request):
    """Expose site-level SEO values to every template."""
    return {
        "SITE_URL": settings.SITE_URL.rstrip("/"),
        "SITE_NAME": settings.SITE_NAME,
        "SEO_FAQS": SEO_FAQS,
    }