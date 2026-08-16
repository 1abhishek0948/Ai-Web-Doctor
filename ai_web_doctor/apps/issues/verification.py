"""Objective, deterministic verification of a single issue (Part 8).

Verification never asks an AI whether a measurable problem is fixed. Instead it
re-runs the same deterministic check that originally flagged the issue and
compares the before/after measurements:

* ``verified`` — the measurement is gone (e.g. overflow 42px -> 0px)
* ``improved`` — the measurement shrank but the problem is still present
* ``failed`` — the measurement is unchanged or worse

This module contains only pure, browser-free logic (value extraction, finding
matching, status classification) so it can be unit-tested without Playwright.
The browser work lives in :mod:`apps.issues.services`.
"""

from __future__ import annotations

from typing import Any

from apps.issues.models import VerificationStatus

# check -> evidence key holding the measurable pixel value.
NUMERIC_VALUE_KEYS = {
    "horizontal_overflow": "overflow_px",
    "navigation_overflow": "overflow_px",
    "text_overflow": "clipped_px",
}

# Checks with a binary outcome (detected / not detected).
BINARY_CHECKS = frozenset({"broken_image", "missing_image_alt"})

# Every deterministic check the scanner can produce and verify.
KNOWN_CHECKS = frozenset(
    set(NUMERIC_VALUE_KEYS)
    | BINARY_CHECKS
    | {"element_outside_viewport"}
) | {"axe"}

# Human-readable label used in before/after copy for each measurable check.
CHECK_LABELS = {
    "horizontal_overflow": "Horizontal overflow",
    "element_outside_viewport": "Element outside viewport",
    "text_overflow": "Text clipped",
    "navigation_overflow": "Navigation overflow",
    "broken_image": "Broken image",
    "missing_image_alt": "Image missing alt text",
}

BINARY_CHECK_LABELS = {
    "broken_image": "Broken image",
    "missing_image_alt": "Image missing alt text",
}

UNVERIFIABLE_MESSAGE = (
    "This issue has no objective measurement that can be re-checked "
    "automatically, so it cannot be verified with the deterministic scanner."
)


def is_axe_check(check: str) -> bool:
    """Whether a check string is an axe-core accessibility rule."""
    return str(check or "").startswith("axe:")


def is_known_check(check: str) -> bool:
    if is_axe_check(check):
        return True
    return str(check or "") in KNOWN_CHECKS


def check_label(check: str) -> str:
    """A short human label for a check, used in before/after copy."""
    if is_axe_check(check):
        return f"Accessibility: {str(check).split(':', 1)[1]}"
    return CHECK_LABELS.get(str(check or ""), "Issue")


def _element_extent(element: dict[str, Any] | None, viewport_width: int | None) -> int | None:
    """How far an element extends beyond the viewport (px), or None."""
    box = (element or {}).get("box") or {}
    x = box.get("x")
    width = box.get("width")
    if x is None or width is None:
        return None
    if x < -1:
        return abs(int(x))
    if viewport_width is None:
        return None
    return max(0, int(x) + int(width) - int(viewport_width))


def extract_value(check: str, evidence: dict[str, Any] | None, viewport_width: int | None) -> int | None:
    """Extract a numeric measurement from a finding's evidence dict.

    Returns an int for measurable checks, ``1`` for binary checks, or ``None``
    when the evidence does not contain a usable measurement.
    """
    evidence = evidence or {}
    check = str(check or "")
    if is_axe_check(check):
        return 1
    if check == "element_outside_viewport":
        return _element_extent(evidence.get("element"), viewport_width)
    if check in NUMERIC_VALUE_KEYS:
        value = evidence.get(NUMERIC_VALUE_KEYS[check])
        if isinstance(value, (int, float)) and value == value:  # not NaN
            return int(value)
        return None
    if check in BINARY_CHECKS:
        return 1
    return None


def format_value(check: str, value: int | None) -> str:
    """Format a measurement for display, e.g. ``"42px"`` or ``"present"``."""
    if value is None:
        return "—"
    if is_axe_check(check) or check in BINARY_CHECKS:
        return "present" if value > 0 else "absent"
    return f"{value}px"


def find_matching_finding(
    check: str, selector: str, findings: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Find the re-run finding that corresponds to the original issue.

    Matches by check name first; when both the issue and a candidate carry a
    selector, prefers an exact selector match (keeps per-element checks such as
    text overflow attached to the right element).
    """
    candidates = [f for f in findings if str(f.get("check", "")) == check]
    if not candidates:
        return None
    if selector:
        for finding in candidates:
            if finding.get("selector") and finding["selector"] == selector:
                return finding
        for finding in candidates:
            if not finding.get("selector"):
                return finding
    return candidates[0]


def classify(old: int | None, new: int | None) -> VerificationStatus:
    """Classify a before/after measurement into a verification status."""
    if old is None:
        old = 1  # the issue existed, so treat it as present
    if new is None or new <= 0:
        return VerificationStatus.VERIFIED
    if new < old:
        return VerificationStatus.IMPROVED
    return VerificationStatus.FAILED


def build_message(check: str, status: VerificationStatus, old: int | None, new: int | None) -> str:
    """A short human sentence describing the verification outcome."""
    label = check_label(check)
    old_text = format_value(check, old)
    new_text = format_value(check, new)
    if status == VerificationStatus.VERIFIED:
        return f"{label} is no longer detected ({old_text} -> {new_text})."
    if status == VerificationStatus.IMPROVED:
        return f"{label} improved ({old_text} -> {new_text}) but is still present."
    return f"{label} is still detected ({old_text})."
