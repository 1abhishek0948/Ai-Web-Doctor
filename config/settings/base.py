"""Base Django settings for AI Web Doctor.

Shared settings used by all environments (development, production, test).
Environment-specific overrides live in ``development.py`` and ``production.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, ""),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)

# Load environment variables from the .env file at the project root when it
# exists. Environment variables already set in the shell take precedence.
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="")
DEBUG = env("DEBUG")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

if "RENDER_EXTERNAL_HOSTNAME" in os.environ:
    render_host = os.environ["RENDER_EXTERNAL_HOSTNAME"]
    if render_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(render_host)
    render_url = f"https://{render_host}"
    if render_url not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_url)

# Site identity, used for canonical URLs, Open Graph tags, and the sitemap.
# Set SITE_URL to the public production domain (e.g. https://aiwebdoctor.onrender.com).
SITE_URL = env("SITE_URL", default="http://localhost:8000")
if "RENDER_EXTERNAL_HOSTNAME" in os.environ and SITE_URL == "http://localhost:8000":
    SITE_URL = f"https://{os.environ['RENDER_EXTERNAL_HOSTNAME']}"
SITE_NAME = env("SITE_NAME", default="AI Web Doctor")

# Application definition

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.scans",
    "apps.issues",
    "apps.reports",
    "apps.ai",
    "apps.seo",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.seo.middleware.NoIndexMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.seo.context.seo",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database
# ---------------------------------------------------------------------------
# Configured through the DATABASE_URL environment variable, e.g.
#   postgres://user:password@localhost:5432/ai_web_doctor
if env.str("DATABASE_URL", default=""):
    DATABASES = {
        "default": env.db("DATABASE_URL"),
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Authentication
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "landing"
LOGOUT_REDIRECT_URL = "landing"

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (screenshots, uploaded assets)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis / Celery
# Redis / Celery
# Fallback to an empty string if Redis is not configured (e.g., Render free plan).
REDIS_URL = env("REDIS_URL", default="")

# Celery configuration
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
# Fallback to eager mode if CELERY_TASK_ALWAYS_EAGER is set to True OR if no Redis broker is set.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=not bool(CELERY_BROKER_URL))

# Gemini / AI provider configuration.
# See the AI settings block below (Part 6) for the full provider configuration.
AI_PROVIDER = env("AI_PROVIDER", default="gemini")

# Gemini settings
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
GEMINI_MODEL = env("GEMINI_MODEL", default="gemini-3.6-flash")
GEMINI_TIMEOUT_MS = env.int("GEMINI_TIMEOUT_MS", default=60_000)
GEMINI_MAX_RETRIES = env.int("GEMINI_MAX_RETRIES", default=2)

# OpenRouter settings
OPENROUTER_API_KEY = env("OPENROUTER_API_KEY", default="")
OPENROUTER_MODEL = env("OPENROUTER_MODEL", default="nvidia/nemotron-3-ultra-550b-a55b:free")
OPENROUTER_TIMEOUT_MS = env.int("OPENROUTER_TIMEOUT_MS", default=120_000)
OPENROUTER_MAX_RETRIES = env.int("OPENROUTER_MAX_RETRIES", default=2)

# Application limits (used from Part 2 onwards).
MAX_SCAN_DURATION = env.int("MAX_SCAN_DURATION", default=120)
MAX_CONCURRENT_SCANS = env.int("MAX_CONCURRENT_SCANS", default=2)

# Scanner resource limits
MAX_REDIRECTS = env.int("MAX_REDIRECTS", default=5)
MAX_RESPONSE_SIZE = env.int("MAX_RESPONSE_SIZE", default=5 * 1024 * 1024)
MAX_SCREENSHOTS = env.int("MAX_SCREENSHOTS", default=16)
# Per-screenshot storage cap (bytes). Oversized screenshots are re-compressed;
# if they still do not fit they are not stored.
MAX_SCREENSHOT_SIZE = env.int("MAX_SCREENSHOT_SIZE", default=8 * 1024 * 1024)
# Total size cap for a single AI request payload (base64 images + prompt text).
MAX_AI_REQUEST_SIZE = env.int("MAX_AI_REQUEST_SIZE", default=4 * 1024 * 1024)

# Per-day scan quota (configurable). Anonymous users share a quota keyed by IP.
RATE_LIMIT_ANONYMOUS_SCANS_PER_DAY = env.int("RATE_LIMIT_ANONYMOUS_SCANS_PER_DAY", default=20)
RATE_LIMIT_AUTHED_SCANS_PER_DAY = env.int("RATE_LIMIT_AUTHED_SCANS_PER_DAY", default=10)
# When the app runs behind a trusted proxy, allow the first X-Forwarded-For
# entry to be treated as the client IP for rate limiting.
TRUST_X_FORWARDED_FOR = env.bool("TRUST_X_FORWARDED_FOR", default=False)

# Playwright browser behavior
PLAYWRIGHT_HEADLESS = env.bool("PLAYWRIGHT_HEADLESS", default=True)
SCAN_PAGE_TIMEOUT_MS = env.int("SCAN_PAGE_TIMEOUT_MS", default=30_000)
# Short bounded idle wait: most pages settle in ~1.5s; never block a viewport
# for the full budget. This is the single biggest per-viewport time saver.
SCAN_NETWORK_IDLE_TIMEOUT_MS = env.int("SCAN_NETWORK_IDLE_TIMEOUT_MS", default=1_500)
# Single-process Chromium with capped V8 heaps: fits ~200MB RAM hosts.
CHROMIUM_LOW_MEMORY_MODE = env.bool("CHROMIUM_LOW_MEMORY_MODE", default=True)
# V8 old-space heap cap (MB) for low-memory Chromium launches. 144MB keeps a
# safety margin while fitting comfortably under the free-tier 512MB container.
CHROMIUM_V8_HEAP_MB = env.int("CHROMIUM_V8_HEAP_MB", default=144)
# axe-core viewport policy in low-memory mode: "desktop" runs the (expensive)
# accessibility pass on the desktop viewport only; "all" runs it on every
# viewport. The accessibility pass is the single biggest transient JS spike.
SCAN_AXE_VIEWPORTS = env("SCAN_AXE_VIEWPORTS", default="desktop")
# Cap on elements captured per viewport for the DOM snapshot (transient
# JS-object spike during collection; findings only need a representative set).
SCAN_DOM_SNAPSHOT_LIMIT = env.int("SCAN_DOM_SNAPSHOT_LIMIT", default=80)
# Abort fonts/media/tracker requests during scans (speed + memory). Images,
# CSS and JS still load so responsive/overflow measurements stay accurate.
SCAN_BLOCK_HEAVY_RESOURCES = env.bool("SCAN_BLOCK_HEAVY_RESOURCES", default=True)
# Extreme low-memory mode: also abort image requests. Images drive most of
# Chromium's transient memory on media-heavy sites; enabling this shrinks peak
# RSS substantially at the cost of slightly less accurate responsive checks.
SCAN_BLOCK_IMAGES = env.bool("SCAN_BLOCK_IMAGES", default=False)
# Run scans in a short-lived subprocess instead of a thread inside the web
# worker: Chromium memory is fully released after each scan and an OOM can
# never kill the web process. Falls back to the thread for dev when disabled.
SCAN_SUBPROCESS_MODE = env.bool("SCAN_SUBPROCESS_MODE", default=False)
# Run scans via the DB-polling worker (``python manage.py scan_worker`` on a
# dedicated instance). The web process only marks scans QUEUED in Postgres;
# the worker claims them and executes the scan in-process. No message broker
# needed — this is the production architecture for broker-less hosts.
SCAN_WORKER_MODE = env.bool("SCAN_WORKER_MODE", default=False)

# Viewports scanned, covering mobile, tablet and desktop.
# Overridable via SCAN_VIEWPORTS env var as JSON: "[[320,800],[768,1024]]".
_DEFAULT_VIEWPORTS = [
    (320, 800),
    (375, 812),
    (390, 844),
    (414, 896),
    (600, 960),
    (768, 1024),
    (834, 1112),
    (1024, 1366),
    (1440, 900),
]


def _parse_viewports(raw: str) -> list[tuple[int, int]]:
    pairs = json.loads(raw)
    viewports = [tuple(pair) for pair in pairs if len(pair) == 2]
    if not viewports:
        raise ValueError("SCAN_VIEWPORTS must contain at least one [width, height] pair")
    return viewports


SCAN_VIEWPORTS = (
    _parse_viewports(env("SCAN_VIEWPORTS"))
    if env("SCAN_VIEWPORTS", default="")
    else _DEFAULT_VIEWPORTS
)

# AI analysis (Gemini).
# The AI is text-only by default (AI_SEND_IMAGES=False): screenshots drive
# most input-token cost, so analysis runs on DOM structure + deterministic
# measurements instead. AI_MAX_PROMPT_TOKENS caps the text prompt per request.
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
GEMINI_MODEL = env("GEMINI_MODEL", default="gemini-3.6-flash")
GEMINI_TIMEOUT_MS = env.int("GEMINI_TIMEOUT_MS", default=60_000)
GEMINI_MAX_RETRIES = env.int("GEMINI_MAX_RETRIES", default=2)
AI_REPRESENTATIVE_VIEWPORTS = [(375, 812), (768, 1024), (1440, 900)]
AI_IMAGE_MAX_WIDTH = env.int("AI_IMAGE_MAX_WIDTH", default=1024)
AI_IMAGE_QUALITY = env.int("AI_IMAGE_QUALITY", default=70)
AI_MAX_ISSUES = env.int("AI_MAX_ISSUES", default=20)
AI_MAX_PROMPT_TOKENS = env.int("AI_MAX_PROMPT_TOKENS", default=15_000)
AI_SEND_IMAGES = env.bool("AI_SEND_IMAGES", default=False)
AI_ENABLED = env.bool("AI_ENABLED", default=True)

# Structured logging (JSON lines). See config/logging_config.py.
LOG_LEVEL = env("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "config.logging_config.JsonFormatter"},
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "scanner": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "aiwebdoctor.events": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# Security headers (also validated by ``manage.py check --deploy``).
SECURE_CONTENT_TYPE_NOSNIFF = env.bool("SECURE_CONTENT_TYPE_NOSNIFF", default=True)
X_FRAME_OPTIONS = "DENY"

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}
