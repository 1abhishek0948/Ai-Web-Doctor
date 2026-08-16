"""Views for the accounts application."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render
from django.views.generic.edit import FormView

from apps.seo.seo_data import SEO_FAQS

WORKFLOW = ["Scan", "Diagnose", "Show", "Fix", "Verify"]

EXAMPLE_SCORES = [
    ("Responsive", 78),
    ("Accessibility", 91),
    ("Visual", 86),
    ("Layout", 76),
    ("Typography", 88),
    ("UX", 84),
]


def _landing_json_ld() -> dict:
    site_url = settings.SITE_URL.rstrip("/")
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{site_url}/#website",
                "url": f"{site_url}/",
                "name": settings.SITE_NAME,
                "publisher": {"@id": f"{site_url}/#organization"},
            },
            {
                "@type": "Organization",
                "@id": f"{site_url}/#organization",
                "name": settings.SITE_NAME,
                "url": f"{site_url}/",
                "logo": {
                    "@type": "ImageObject",
                    "url": f"{site_url}/static/img/favicon-32x32.png",
                },
            },
            {
                "@type": "SoftwareApplication",
                "name": settings.SITE_NAME,
                "url": f"{site_url}/",
                "applicationCategory": "DeveloperApplication",
                "operatingSystem": "Web",
                "description": (
                    "Free website UI testing tool that scans any site in a real browser "
                    "across mobile, tablet, and desktop viewports and reports responsive "
                    "design, layout, and accessibility issues."
                ),
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            },
        ],
    }


def _faq_json_ld() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": faq["question"],
                "acceptedAnswer": {"@type": "Answer", "text": faq["answer"]},
            }
            for faq in SEO_FAQS
        ],
    }


def landing(request):
    """Render the public landing page."""
    return render(
        request,
        "pages/landing.html",
        {
            "workflow": WORKFLOW,
            "example_scores": EXAMPLE_SCORES,
            "landing_json": _landing_json_ld(),
            "faq_json": _faq_json_ld(),
        },
    )


class RegisterView(FormView):
    template_name = "accounts/register.html"
    form_class = UserCreationForm

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        messages.success(self.request, "Welcome to AI Web Doctor. Your account was created.")
        return redirect(self.get_success_url())

    def get_success_url(self):
        return self.request.GET.get("next", "landing")
