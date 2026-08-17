"""Daily scan quota (rate limiting) for the scans application.

Anonymous callers are limited per IP address; authenticated callers per
account. Limits are configurable:

* ``RATE_LIMIT_ANONYMOUS_SCANS_PER_DAY`` (default 3)
* ``RATE_LIMIT_AUTHED_SCANS_PER_DAY`` (default 10)

The quota is enforced when a scan is created, before any scanner work starts.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.scans.models import Scan


def get_client_ip(request) -> str | None:
    """Return the best-effort client IP for the current request.

    The ``X-Forwarded-For`` header is only trusted when
    ``TRUST_X_FORWARDED_FOR`` is enabled (i.e. behind a trusted proxy).
    """
    if settings.TRUST_X_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    return request.META.get("REMOTE_ADDR") or None


def scan_quota(request, user=None) -> tuple[int, int]:
    """Return ``(used, limit)`` scans consumed today by the caller."""
    today = timezone.localdate()
    if bool(getattr(user, "is_authenticated", False)):
        used = Scan.objects.filter(user=user, created_at__date=today).count()
        limit = settings.RATE_LIMIT_AUTHED_SCANS_PER_DAY
    else:
        ip = get_client_ip(request)
        used = Scan.objects.filter(
            user__isnull=True, client_ip=ip, created_at__date=today
        ).count()
        limit = settings.RATE_LIMIT_ANONYMOUS_SCANS_PER_DAY
    return int(used), int(limit)


def quota_exceeded(request, user=None) -> tuple[bool, int, int]:
    """Return ``(exceeded, used, limit)`` for the current caller."""
    used, limit = scan_quota(request, user=user)
    return used >= limit, used, limit
