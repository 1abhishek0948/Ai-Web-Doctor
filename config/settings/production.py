"""Production environment settings for AI Web Doctor."""

from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

if not SECRET_KEY:  # noqa: F405
    raise RuntimeError("SECRET_KEY must be set in production.")

# Production-safe scan defaults. These are unconditional: the unsafe base
# defaults (thread scanning, 2 concurrent Chromiums, 10s idle waits) can never
# leak into production, even if env vars or a .env file carry stale values.
SCAN_SUBPROCESS_MODE = True
MAX_CONCURRENT_SCANS = 1
SCAN_NETWORK_IDLE_TIMEOUT_MS = 2_000

# Production should use a real mail backend (SMTP) configured via env vars.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)

# Static files are collected into STATIC_ROOT and served by the web server.
# Note: Django 5.2 requires STORAGES (STATICFILES_STORAGE is ignored).
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}

# Serve static files directly from gunicorn (no separate web server needed).
MIDDLEWARE = ["whitenoise.middleware.WhiteNoiseMiddleware"] + MIDDLEWARE  # noqa: F405

# Basic production hardening. Adjust to match your proxy/load balancer.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=True)
