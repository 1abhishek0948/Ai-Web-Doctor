"""URL configuration for the seo application."""

from __future__ import annotations

from django.urls import path

from apps.seo import views

app_name = "seo"

urlpatterns = [
    path("robots.txt", views.robots_txt, name="robots"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap"),
]