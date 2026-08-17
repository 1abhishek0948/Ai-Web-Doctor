"""Deterministic responsive-layout checks.

These checks are pure measurements, deliberately computed without any AI.
Each returns a normalized finding dict so downstream services (issues, scores,
reports) have a stable shape to consume in later phases.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

CATEGORY_RESPONSIVE = "responsive"


def _finding(
    *,
    check: str,
    title: str,
    severity: str,
    viewport_width: int,
    description: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "check": check,
        "category": CATEGORY_RESPONSIVE,
        "title": title,
        "severity": severity,
        "viewport_width": viewport_width,
        "description": description,
        "evidence": evidence or {},
    }


def detect_horizontal_overflow(metrics: dict[str, int]) -> dict[str, Any] | None:
    """Detect horizontal overflow when the document is wider than the viewport.

    ``metrics`` must contain at least ``innerWidth`` and ``scrollWidth``.
    Returns a finding dict or ``None`` when there is no overflow.
    """
    viewport_width = metrics["innerWidth"]
    document_width = metrics["scrollWidth"]
    overflow = document_width - viewport_width

    if overflow <= 0:
        return None

    return _finding(
        check="horizontal_overflow",
        title=f"Horizontal overflow at {viewport_width}px",
        severity="high",
        viewport_width=viewport_width,
        description=(
            f"Horizontal overflow detected. The document is {document_width}px "
            f"wide but the viewport is only {viewport_width}px."
        ),
        evidence={
            "viewport_width": viewport_width,
            "document_width": document_width,
            "overflow_px": overflow,
        },
    )


def compute_overflow_px(metrics: dict[str, int]) -> int:
    """Return the raw overflow in pixels (0 when none)."""
    return max(0, metrics["scrollWidth"] - metrics["innerWidth"])


ELEMENTS_OUTSIDE_SCRIPT = """
() => {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const out = [];
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let el;
  while ((el = walker.nextNode()) && out.length < 100) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    if (style.position === "fixed" && rect.left === 0 && rect.top === 0) continue;
    if (seen.has(el.tagName + ":" + el.className)) continue;
    seen.add(el.tagName + ":" + el.className);
    if (rect.left < -1 || rect.right > vw + 1) {
      out.push({
        tag: el.tagName.toLowerCase(),
        id: el.id || "",
        classes: String(el.className || "").split(/\\s+/).filter(Boolean).slice(0, 6),
        box: {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        },
      });
    }
  }
  return out;
}
"""


def detect_elements_outside_viewport(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Find visible elements whose bounding boxes leave the viewport width."""
    try:
        elements = page.evaluate(ELEMENTS_OUTSIDE_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate element-overflow script.")
        return []

    viewport_width = metrics["innerWidth"]
    viewport_height = metrics["innerHeight"]
    findings: list[dict[str, Any]] = []
    for el in elements[:10]:
        box = el["box"]
        right = box["x"] + box["width"]
        left = box["x"]
        if left < -1:
            msg = f"Element extends {abs(left)}px beyond the left edge"
        else:
            msg = f"Element extends {right - viewport_width}px beyond the right edge"
        findings.append(
            _finding(
                check="element_outside_viewport",
                title=f"Element outside viewport at {viewport_width}px",
                severity="medium",
                viewport_width=viewport_width,
                description=f"{el['tag']} {msg}.",
                evidence={"element": el},
            )
        )
    return findings


TEXT_OVERFLOW_SCRIPT = """
() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let el;
  while ((el = walker.nextNode()) && out.length < 20) {
    const text = (el.innerText || "").trim();
    if (text.length < 3) continue;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    if (style.position === "fixed") continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    const overflowsX = el.scrollWidth > el.clientWidth + 1;
    const overflowsY = el.scrollHeight > el.clientHeight + 1;
    if (!overflowsX && !overflowsY) continue;
    if (style.overflow === "hidden" && !overflowsX && !overflowsY) continue;
    out.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || "",
      classes: String(el.className || "").split(/\\s+/).filter(Boolean).slice(0, 6),
      text: text.slice(0, 80),
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      overflowX: style.overflowX,
      overflowY: style.overflowY,
      box: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
    });
  }
  return out;
}
"""


def detect_text_overflow(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Find elements whose own content overflows their bounding box."""
    try:
        elements = page.evaluate(TEXT_OVERFLOW_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate text-overflow script.")
        return []

    viewport_width = metrics["innerWidth"]
    viewport_height = metrics["innerHeight"]
    findings: list[dict[str, Any]] = []
    for el in elements[:10]:
        clipped_px = max(
            0,
            el["scrollWidth"] - el["clientWidth"],
            el["scrollHeight"] - el["clientHeight"],
        )
        if clipped_px < 3:
            continue
        selector = f"{el['tag']}{('#' + el['id']) if el['id'] else ''}"
        findings.append(
            {
                "check": "text_overflow",
                "category": "layout",
                "title": f"Text clipped at {viewport_width}px",
                "severity": "medium",
                "viewport_width": viewport_width,
                "viewport_height": viewport_height,
                "description": (
                    f"A {el['tag']} element clips its text by ~{clipped_px}px "
                    f"(container {el['clientWidth']}px, content {el['scrollWidth']}px)."
                ),
                "selector": selector,
                "evidence": {
                    "element": el,
                    "clipped_px": clipped_px,
                },
                "confidence": 1.0,
                "source": "deterministic",
            }
        )
    return findings


IMAGE_ISSUES_SCRIPT = """
() => {
  const out = [];
  const imgs = Array.from(document.querySelectorAll("img"));
  for (const img of imgs) {
    const rect = img.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    const broken = img.complete && img.naturalWidth === 0;
    const noAlt = !img.hasAttribute("alt");
    if (!broken && !noAlt) continue;
    out.push({
      src: (img.getAttribute("src") || "").slice(0, 200),
      alt: (img.getAttribute("alt") || "").slice(0, 80),
      hasAlt: img.hasAttribute("alt"),
      broken,
      box: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
    });
  }
  return out;
}
"""


def detect_image_issues(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Find broken images (failed to load) and images missing an alt attribute.

    Missing-alt is an objective measurement (attribute absence) and is reported
    under the accessibility category; axe-core confirms the same rule and the
    dedup step merges the two sources into one combined issue.
    """
    try:
        images = page.evaluate(IMAGE_ISSUES_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate image-issues script.")
        return []

    viewport_width = metrics["innerWidth"]
    viewport_height = metrics["innerHeight"]
    findings: list[dict[str, Any]] = []
    for img in images[:10]:
        if img["broken"]:
            findings.append(
                {
                    "check": "broken_image",
                    "category": "layout",
                    "title": f"Broken image at {viewport_width}px",
                    "severity": "low",
                    "viewport_width": viewport_width,
                    "viewport_height": viewport_height,
                    "description": (
                        "An image failed to load (naturalWidth is 0). "
                        f"src={img['src']!r}."
                    ),
                    "selector": f"img[src^={img['src'][:40]!r}]",
                    "evidence": {"image": img},
                    "confidence": 1.0,
                    "source": "deterministic",
                }
            )
        elif not img["hasAlt"]:
            findings.append(
                {
                    "check": "missing_image_alt",
                    "category": "accessibility",
                    "title": f"Image missing alt text at {viewport_width}px",
                    "severity": "medium",
                    "viewport_width": viewport_width,
                    "viewport_height": viewport_height,
                    "description": (
                        "An image has no alt attribute, so screen readers and "
                        "search engines cannot describe it."
                    ),
                    "selector": f"img[src^={img['src'][:40]!r}]",
                    "evidence": {"image": img},
                    "confidence": 1.0,
                    "source": "deterministic",
                }
            )
    return findings


NAV_OVERFLOW_SCRIPT = """
() => {
  const out = [];
  const nodes = document.querySelectorAll("nav, header, [role='navigation']");
  for (const el of Array.from(nodes)) {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    out.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || "",
      classes: String(el.className || "").split(/\\s+/).filter(Boolean).slice(0, 6),
      box: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
    });
  }
  return out;
}
"""


def detect_navigation_overflow(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Find navigation elements that overflow the viewport width."""
    try:
        navs = page.evaluate(NAV_OVERFLOW_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate navigation-overflow script.")
        return []

    viewport_width = metrics["innerWidth"]
    viewport_height = metrics["innerHeight"]
    findings: list[dict[str, Any]] = []
    for nav in navs[:5]:
        box = nav["box"]
        right = box["x"] + box["width"]
        if right > viewport_width + 1 or box["x"] < -1:
            overflow = max(right - viewport_width, abs(box["x"]))
            findings.append(
                {
                    "check": "navigation_overflow",
                    "category": "navigation",
                    "title": f"Navigation overflows at {viewport_width}px",
                    "severity": "high",
                    "viewport_width": viewport_width,
                    "viewport_height": viewport_height,
                    "description": (
                        f"Navigation ({nav['tag']}) extends {overflow}px beyond "
                        f"the {viewport_width}px viewport."
                    ),
                    "selector": f"{nav['tag']}{('#' + nav['id']) if nav['id'] else ''}",
                    "evidence": {"element": nav, "overflow_px": overflow},
                    "confidence": 1.0,
                    "source": "deterministic",
                }
            )
    return findings


def detect_all(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Run every deterministic responsive detector and return all findings."""
    findings: list[dict[str, Any]] = []
    overflow = detect_horizontal_overflow(metrics)
    if overflow:
        findings.append(overflow)
    findings.extend(detect_elements_outside_viewport(page, metrics))
    findings.extend(detect_text_overflow(page, metrics))
    findings.extend(detect_image_issues(page, metrics))
    findings.extend(detect_navigation_overflow(page, metrics))
    return findings
