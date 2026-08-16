"""Automated accessibility checks via axe-core.

axe-core is injected into the scanned page, run per viewport, and its
violations are normalized into the shared finding shape with
``source = "accessibility"`` and ``category = "accessibility"``.

The module degrades gracefully: if axe-core cannot be loaded (offline, CSP, or
CDN unavailable), accessibility findings are simply omitted — the deterministic
scan never fails because of it.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.sync_api import Page

from config.logging_config import log_event

logger = logging.getLogger(__name__)

AXE_CDN_SOURCES = (
    "https://cdn.jsdelivr.net/npm/axe-core@4.10.0/axe.min.js",
    "https://unpkg.com/axe-core@4.10.0/axe.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.0/axe.min.js",
)

IMPACT_TO_SEVERITY = {
    "critical": "critical",
    "serious": "high",
    "moderate": "medium",
    "minor": "low",
}

# Return only meaningful violation fields; avoid dumping huge DOM fragments.
VIOLATION_FIELDS = ("id", "impact", "help", "helpUrl", "tags", "nodes")

AXE_RUN_SCRIPT = """
async (options) => {
  if (typeof axe === "undefined") {
    return { skipped: true, reason: "axe not loaded" };
  }
  try {
    const results = await axe.run(document, options);
    return {
      violations: results.violations || [],
      incomplete: results.incomplete || [],
      passes: (results.passes || []).length,
    };
  } catch (err) {
    return { skipped: true, reason: String(err && err.message || err) };
  }
}
"""


def _normalize_violation(
    violation: dict[str, Any], viewport_width: int, viewport_height: int
) -> dict[str, Any] | None:
    impact = violation.get("impact") or "moderate"
    severity = IMPACT_TO_SEVERITY.get(impact, "medium")
    nodes = violation.get("nodes") or []
    if not nodes:
        return None

    node = nodes[0]
    target = node.get("target") or []
    selector = " ".join(target) if isinstance(target, list) else str(target or "")
    snippet = (node.get("html") or "")[:300]

    return {
        "check": f"axe:{violation.get('id', 'unknown')}",
        "category": "accessibility",
        "title": violation.get("help") or violation.get("id", "Accessibility issue"),
        "severity": severity,
        "viewport_width": viewport_width,
        "viewport_height": viewport_height,
        "description": (
            f"{violation.get('help') or 'Accessibility issue'} "
            f"(rule {violation.get('id')}, impact {impact})."
        ),
        "selector": selector,
        "evidence": {
            "rule_id": violation.get("id"),
            "impact": impact,
            "help_url": violation.get("helpUrl"),
            "tags": violation.get("tags") or [],
            "node_count": len(nodes),
            "snippet": snippet,
            "target": target,
        },
        "confidence": 1.0,
        "source": "accessibility",
    }


def _inject_axe(page: Page) -> bool:
    for source in AXE_CDN_SOURCES:
        try:
            page.add_script_tag(url=source)
            loaded = page.evaluate("typeof axe !== 'undefined'")
            if loaded:
                return True
        except Exception:  # noqa: BLE001
            logger.info("axe-core failed to load from %s", source)
    return False


def detect_accessibility(
    page: Page, viewport_width: int, viewport_height: int
) -> list[dict[str, Any]]:
    """Run axe-core and return normalized accessibility findings."""
    if not _inject_axe(page):
        logger.warning("axe-core could not be loaded; skipping accessibility checks.")
        log_event("accessibility.error", level=logging.WARNING, reason="axe_not_loaded")
        return []

    try:
        result = page.evaluate(
            AXE_RUN_SCRIPT,
            {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa"]}},
        )
    except Exception:  # noqa: BLE001
        logger.warning("axe.run() failed; skipping accessibility checks.")
        log_event("accessibility.error", level=logging.WARNING, reason="axe_run_failed")
        return []

    if not isinstance(result, dict) or result.get("skipped"):
        logger.warning("axe.run() skipped: %s", (result or {}).get("reason"))
        log_event(
            "accessibility.error",
            level=logging.WARNING,
            reason=str((result or {}).get("reason"))[:200],
        )
        return []

    findings: list[dict[str, Any]] = []
    for violation in result.get("violations") or []:
        finding = _normalize_violation(violation, viewport_width, viewport_height)
        if finding is not None:
            findings.append(finding)
    return findings
