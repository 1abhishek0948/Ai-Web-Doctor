"""Normalized finding primitives shared by every detection source.

Each detector returns plain dicts in a stable shape so downstream services can
build :class:`apps.issues.models.Issue` rows without caring which source
produced them.
"""

from __future__ import annotations

from typing import Any

SOURCE_DETERMINISTIC = "deterministic"
SOURCE_ACCESSIBILITY = "accessibility"
SOURCE_AI = "ai"
SOURCE_COMBINED = "combined"

VALID_SEVERITIES = ("critical", "high", "medium", "low", "info")

VALID_CATEGORIES = (
    "responsive",
    "layout",
    "spacing",
    "typography",
    "color",
    "accessibility",
    "navigation",
    "interaction",
    "performance",
    "ux",
)


def make_finding(
    *,
    check: str,
    category: str,
    title: str,
    severity: str,
    description: str,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
    selector: str = "",
    evidence: dict[str, Any] | None = None,
    confidence: float = 1.0,
    source: str = SOURCE_DETERMINISTIC,
) -> dict[str, Any]:
    """Return a normalized finding dict.

    Severity/category are validated so a bad detector can never poison the
    database with an unknown choice.
    """
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"Unknown severity: {severity!r}")
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Unknown category: {category!r}")
    return {
        "check": check,
        "category": category,
        "title": title,
        "severity": severity,
        "description": description,
        "viewport_width": viewport_width,
        "viewport_height": viewport_height,
        "selector": selector,
        "evidence": evidence or {},
        "confidence": confidence,
        "source": source,
    }
