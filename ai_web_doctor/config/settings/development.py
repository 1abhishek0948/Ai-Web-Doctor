"""Development environment settings for AI Web Doctor."""

from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True

# The default secret key is only acceptable for local development.
SECRET_KEY = env("SECRET_KEY", default="django-insecure-dev-only-not-for-production")

ALLOWED_HOSTS = ["*"]

# Email backend that writes to the console during development.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
