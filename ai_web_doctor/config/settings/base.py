"""Base Django settings for AI Web Doctor.

Shared settings used by all environments (development, production, test).
Environment-specific overrides live in ``development.py`` and ``production.py``.
"""

from __future__ import annotations

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

# Site identity, used for canonical URLs, Open Graph tags, and the sitemap.
# Set SITE_URL to the public production domain (e.g. https://aiwebdoctor.onrender.com).
SITE_URL = env("SITE_URL", default="http://localhost:8000")
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
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"postgres://postgres:postgres@localhost:5432/ai_web_doctor",
    ),
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
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (screenshots, uploaded assets)
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis / Celery
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

# Celery configuration
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env("CELERY_TASK_ALWAYS_EAGER", default=DEBUG)

# Gemini / AI provider configuration.
# See the AI settings block below (Part 6) for the full provider configuration.
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
RATE_LIMIT_ANONYMOUS_SCANS_PER_DAY = env.int("RATE_LIMIT_ANONYMOUS_SCANS_PER_DAY", default=3)
RATE_LIMIT_AUTHED_SCANS_PER_DAY = env.int("RATE_LIMIT_AUTHED_SCANS_PER_DAY", default=10)
# When the app runs behind a trusted proxy, allow the first X-Forwarded-For
# entry to be treated as the client IP for rate limiting.
TRUST_X_FORWARDED_FOR = env.bool("TRUST_X_FORWARDED_FOR", default=False)

# Playwright browser behavior
PLAYWRIGHT_HEADLESS = env.bool("PLAYWRIGHT_HEADLESS", default=True)
SCAN_PAGE_TIMEOUT_MS = env.int("SCAN_PAGE_TIMEOUT_MS", default=30_000)
SCAN_NETWORK_IDLE_TIMEOUT_MS = env.int("SCAN_NETWORK_IDLE_TIMEOUT_MS", default=10_000)

# Viewports scanned, covering mobile, tablet and desktop.
SCAN_VIEWPORTS = [
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

# AI visual analysis (Gemini).
# Representative viewports always sent to the model; the deterministic scanner
# also adds screenshots for viewports where it found important problems.
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
GEMINI_MODEL = env("GEMINI_MODEL", default="gemini-2.0-flash")
GEMINI_TIMEOUT_MS = env.int("GEMINI_TIMEOUT_MS", default=45_000)
GEMINI_MAX_RETRIES = env.int("GEMINI_MAX_RETRIES", default=1)
AI_REPRESENTATIVE_VIEWPORTS = [(375, 812), (768, 1024), (1440, 900)]
AI_IMAGE_MAX_WIDTH = env.int("AI_IMAGE_MAX_WIDTH", default=1024)
AI_IMAGE_QUALITY = env.int("AI_IMAGE_QUALITY", default=70)
AI_MAX_ISSUES = env.int("AI_MAX_ISSUES", default=20)
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
