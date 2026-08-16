"""Middleware that prevents thin or private pages from being indexed."""

from __future__ import annotations

NOINDEX_FOLLOW_PREFIXES = ("/scans/",)
NOINDEX_NOFOLLOW_PREFIXES = ("/accounts/", "/admin/", "/api/")


class NoIndexMiddleware:
    """Tag private/user-generated pages with X-Robots-Tag and request.seo_robots.

    Scan reports are user-generated, thin content: they stay noindex,follow so
    links within them still pass value. Auth, admin, and API pages are
    noindex,nofollow.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        robots = None
        if path.startswith(NOINDEX_NOFOLLOW_PREFIXES):
            robots = "noindex, nofollow"
        elif path.startswith(NOINDEX_FOLLOW_PREFIXES):
            robots = "noindex, follow"
        request.seo_robots = robots
        response = self.get_response(request)
        if robots:
            response["X-Robots-Tag"] = robots
        return response