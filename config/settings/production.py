"""Production environment settings for AI Web Doctor."""

from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

if not SECRET_KEY:  # noqa: F405
    raise RuntimeError("SECRET_KEY must be set in production.")

# Production-safe scan defaults. Concurrency and idle-wait are hard-forced
# below. Render's Free Tier no longer supports background workers, so scans
# run in a short-lived subprocess on the web instance. The subprocess isolates
# Chromium: its memory is fully released after each scan, and an OOM in the
# child never kills gunicorn. Memory-saving flags (CHROMIUM_LOW_MEMORY_MODE,
# SCAN_BLOCK_IMAGES) keep peak RSS under the 512 MB container limit.
SCAN_SUBPROCESS_MODE = env.bool("SCAN_SUBPROCESS_MODE", default=True)
# Disabled by default: no dedicated worker service on the free tier.
SCAN_WORKER_MODE = env.bool("SCAN_WORKER_MODE", default=False)
MAX_CONCURRENT_SCANS = 1
SCAN_NETWORK_IDLE_TIMEOUT_MS = 2_000

# Production should use a real mail backend (SMTP) configured via env vars.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="webmaster@localhost")

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
