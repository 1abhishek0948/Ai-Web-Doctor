"""URL configuration for the accounts application."""

from __future__ import annotations

from django.urls import path

from apps.accounts.views import RegisterView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
]
