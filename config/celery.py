"""Celery application configuration for AI Web Doctor.

The Celery app is created lazily. ``config.celery`` is imported by Django at
startup so that tasks defined anywhere in the project are discovered
automatically.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("ai_web_doctor")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
