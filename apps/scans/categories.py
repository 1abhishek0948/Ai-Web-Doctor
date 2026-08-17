"""Category grouping and mapping for the results dashboard.

Ten raw issue categories are reported by the scanner; the scoring system
organizes them into six groups whose weights sum to 100. This module is the
single source of truth for that mapping so the dashboard, scoring service and
templates never hardcode category lists.

* ``DETERMINISTIC_CATEGORIES`` — categories the Playwright checks can report.
* ``AI_ONLY_CATEGORIES`` — categories only detectable by visual (AI) reasoning.
  A zero-count card for one of these means "not analyzed" unless AI ran.
* ``CATEGORY_TO_GROUP`` — raw category -> scoring group.
"""

from __future__ import annotations

CATEGORY_GROUPS = {
    "responsive": {"label": "Responsive", "weight": 25},
    "accessibility": {"label": "Accessibility", "weight": 20},
    "visual": {"label": "Visual", "weight": 20},
    "layout": {"label": "Layout", "weight": 15},
    "typography": {"label": "Typography", "weight": 10},
    "ux": {"label": "UX", "weight": 10},
}

GROUP_ORDER = tuple(CATEGORY_GROUPS.keys())

CATEGORY_TO_GROUP = {
    "responsive": "responsive",
    "accessibility": "accessibility",
    "layout": "layout",
    "typography": "typography",
    "spacing": "visual",
    "color": "visual",
    "interaction": "visual",
    "performance": "visual",
    "navigation": "ux",
    "ux": "ux",
}

# Categories only detectable by visual (AI) reasoning; deterministic checks can
# never report them, so a zero-count card is "not analyzed yet" when AI is off.
AI_ONLY_CATEGORIES = {"spacing", "color", "typography", "interaction", "performance", "ux"}

# Categories the deterministic scanner can report on its own.
DETERMINISTIC_CATEGORIES = {"responsive", "layout", "navigation", "accessibility"}

# Backwards-compatible alias used by earlier code paths.
VISUAL_CATEGORIES = AI_ONLY_CATEGORIES


def category_group(category: str) -> str:
    """Return the scoring group for a raw category (falls back to itself)."""
    return CATEGORY_TO_GROUP.get(category, category)


def group_label(group: str) -> str:
    return CATEGORY_GROUPS.get(group, {}).get("label", group.title())


def group_weight(group: str) -> int:
    return CATEGORY_GROUPS.get(group, {}).get("weight", 0)


def members(group: str) -> tuple[str, ...]:
    """Return the raw categories that belong to a scoring group."""
    return tuple(
        category
        for category, g in CATEGORY_TO_GROUP.items()
        if g == group
    )