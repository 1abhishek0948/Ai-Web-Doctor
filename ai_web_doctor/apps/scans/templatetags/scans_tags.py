"""Template tags for the scans application."""

from __future__ import annotations

from django import template

register = template.Library()


@register.filter
def get_item(mapping: dict, key):
    """Return ``mapping[key]`` or ``None`` when missing (dict access in templates)."""
    if mapping is None:
        return None
    return mapping.get(key)


@register.filter
def health_label(score):
    """A human label for a 0-100 UI Health score."""
    if score is None:
        return "Pending"
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Fair"
    if score >= 40:
        return "Poor"
    return "Critical"


@register.filter
def health_color(score):
    """Tailwind badge classes for a 0-100 UI Health score."""
    if score is None:
        return "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
    if score >= 90:
        return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300"
    if score >= 75:
        return "bg-lime-100 text-lime-700 dark:bg-lime-900 dark:text-lime-300"
    if score >= 60:
        return "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300"
    if score >= 40:
        return "bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300"
    return "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"


@register.filter
def severity_badge(severity):
    """Tailwind badge classes for an issue severity."""
    mapping = {
        "critical": "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
        "high": "bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300",
        "medium": "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300",
        "low": "bg-sky-100 text-sky-700 dark:bg-sky-900 dark:text-sky-300",
        "info": "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    }
    return mapping.get(severity, mapping["info"])


@register.filter
def source_label(source):
    """Human label for an issue source."""
    labels = {
        "deterministic": "Deterministic",
        "accessibility": "Accessibility",
        "ai": "AI",
        "combined": "AI + Deterministic",
    }
    return labels.get(source, source)


@register.filter
def ai_status_label(status):
    """Human label for the machine-readable Scan.ai_status value."""
    labels = {
        "pending": "Pending",
        "running": "Running",
        "completed": "Completed",
        "unavailable": "Unavailable",
        "failed": "Failed",
        "rate_limited": "Rate limited",
        "skipped": "Skipped",
    }
    return labels.get(status, status)


@register.filter
def analysis_state_label(state):
    """Human label for a category/group analysis state."""
    labels = {
        "analyzed": "Analyzed",
        "not_analyzed": "Not analyzed",
        "failed": "Analysis failed",
        "partial": "Partial",
    }
    return labels.get(state, state)
