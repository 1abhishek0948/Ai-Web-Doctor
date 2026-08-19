"""Deterministic visual-design checks.

Pure measurements computed in-browser (computed styles + bounding boxes),
deliberately without any AI, so the six categories that were previously
AI-only — typography, color, spacing, interaction, performance, ux — are
analyzed on every scan. Each check returns normalized finding dicts with the
same stable shape as :mod:`scanner.responsive`.

All checks run once per scan at the desktop viewport: they are
viewport-independent, so per-viewport reruns would only multiply counts.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

MAX_SMALL_TARGETS = 10
MAX_FINDINGS = 5

TINY_TEXT_SCRIPT = """
() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let el;
  while ((el = walker.nextNode()) && out.length < 5) {
    const text = (el.innerText || "").trim();
    if (text.length < 3) continue;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    if (style.position === "fixed") continue;
    const size = parseFloat(style.fontSize);
    if (!size || size >= 12) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    if (el.children.length > 3) continue;
    out.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || "",
      classes: String(el.className || "").split(/\\s+/).filter(Boolean).slice(0, 6),
      text: text.slice(0, 80),
      fontSize: style.fontSize,
      box: {
        x: Math.round(rect.x), y: Math.round(rect.y),
        width: Math.round(rect.width), height: Math.round(rect.height),
      },
    });
  }
  return out;
}
"""

FONT_SCALE_SCRIPT = """
() => {
  const sizes = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let el;
  while ((el = walker.nextNode()) && sizes.size < 40) {
    const text = (el.innerText || "").trim();
    if (text.length < 3) continue;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    if (style.position === "fixed") continue;
    const size = parseFloat(style.fontSize);
    if (size && size > 0) sizes.add(Math.round(size));
  }
  return { count: sizes.size, sizes: Array.from(sizes).sort((a, b) => a - b) };
}
"""

INVISIBLE_TEXT_SCRIPT = """
() => {
  const rgba = (str) => {
    const s = (str || "").trim();
    if (s === "transparent") return [0, 0, 0, 0];
    const m = s.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return null;
    const p = m[1].split(",").map((x) => parseFloat(x));
    return [p[0] || 0, p[1] || 0, p[2] || 0, p.length > 3 ? p[3] : 1];
  };
  const same = (a, b) =>
    a && b && a[0] === b[0] && a[1] === b[1] && a[2] === b[2] &&
    a[3] > 0 && b[3] > 0;
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let el;
  while ((el = walker.nextNode()) && out.length < 5) {
    const text = (el.innerText || "").trim();
    if (text.length < 2) continue;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    const c = rgba(style.color);
    const b = rgba(style.backgroundColor);
    if (same(c, b)) {
      out.push({
        tag: el.tagName.toLowerCase(),
        id: el.id || "",
        classes: String(el.className || "").split(/\\s+/).filter(Boolean).slice(0, 6),
        text: text.slice(0, 60),
        color: style.color,
        backgroundColor: style.backgroundColor,
        box: {
          x: Math.round(rect.x), y: Math.round(rect.y),
          width: Math.round(rect.width), height: Math.round(rect.height),
        },
      });
    }
  }
  return out;
}
"""

OVERLAPPING_SIBLINGS_SCRIPT = """
() => {
  const out = [];
  let checked = 0;
  const isCandidate = (el) => {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    if (style.position === "fixed" || style.position === "absolute") return false;
    const rect = el.getBoundingClientRect();
    return rect.width >= 2 && rect.height >= 2;
  };
  const describe = (el) => {
    const rect = el.getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      id: el.id || "",
      classes: String(el.className || "").split(/\\s+/).filter(Boolean).slice(0, 6),
      box: {
        x: Math.round(rect.x), y: Math.round(rect.y),
        width: Math.round(rect.width), height: Math.round(rect.height),
      },
    };
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let el;
  while ((el = walker.nextNode()) && out.length < 5 && checked < 400) {
    checked++;
    const children = Array.from(el.children).filter(isCandidate);
    if (children.length < 2) continue;
    for (let i = 0; i < children.length && out.length < 5; i++) {
      for (let j = i + 1; j < children.length && out.length < 5; j++) {
        const ar = children[i].getBoundingClientRect();
        const br = children[j].getBoundingClientRect();
        const ox = Math.min(ar.x + ar.width, br.x + br.width) - Math.max(ar.x, br.x);
        const oy = Math.min(ar.y + ar.height, br.y + br.height) - Math.max(ar.y, br.y);
        if (ox <= 8 || oy <= 8) continue;
        if (ox >= ar.width || ox >= br.width) continue;
        out.push({
          parent: describe(el),
          a: describe(children[i]),
          b: describe(children[j]),
          overlap: { x: Math.round(ox), y: Math.round(oy) },
        });
        break;
      }
    }
  }
  return out;
}
"""

SMALL_TARGET_SCRIPT = """
() => {
  const out = [];
  const targets = Array.from(document.querySelectorAll(
    "a[href], button, input, select, textarea, [role='button']"
  ));
  for (const el of targets) {
    if (out.length >= 10) break;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    if (rect.width >= 44 && rect.height >= 44) continue;
    const text = (el.innerText || "").trim().replace(/\\s+/g, " ").slice(0, 60);
    out.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || "",
      classes: String(el.className || "").split(/\\s+/).filter(Boolean).slice(0, 6),
      text: text || (el.getAttribute("aria-label") || "").slice(0, 60),
      box: {
        x: Math.round(rect.x), y: Math.round(rect.y),
        width: Math.round(rect.width), height: Math.round(rect.height),
      },
    });
  }
  return out;
}
"""

POINTER_CURSOR_SCRIPT = """
() => {
  const out = [];
  const targets = Array.from(document.querySelectorAll(
    "a[href], button, [role='button']"
  ));
  for (const el of targets) {
    if (out.length >= 5) break;
    if (el.disabled) continue;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    if (style.cursor === "pointer") continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    const text = (el.innerText || "").trim().replace(/\\s+/g, " ").slice(0, 60);
    out.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || "",
      classes: String(el.className || "").split(/\\s+/).filter(Boolean).slice(0, 6),
      text: text || (el.getAttribute("aria-label") || "").slice(0, 60),
      box: {
        x: Math.round(rect.x), y: Math.round(rect.y),
        width: Math.round(rect.width), height: Math.round(rect.height),
      },
    });
  }
  return out;
}
"""

IMAGE_DIMENSIONS_SCRIPT = """
() => {
  const out = [];
  const imgs = Array.from(document.querySelectorAll("img"));
  for (const img of imgs) {
    if (out.length >= 5) break;
    const rect = img.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    const hasW = img.hasAttribute("width");
    const hasH = img.hasAttribute("height");
    if (hasW && hasH) continue;
    out.push({
      src: (img.getAttribute("src") || "").slice(0, 200),
      hasWidth: hasW,
      hasHeight: hasH,
      box: {
        x: Math.round(rect.x), y: Math.round(rect.y),
        width: Math.round(rect.width), height: Math.round(rect.height),
      },
    });
  }
  return out;
}
"""

OVERSIZED_IMAGE_SCRIPT = """
() => {
  const out = [];
  const imgs = Array.from(document.querySelectorAll("img"));
  for (const img of imgs) {
    if (out.length >= 5) break;
    if (!img.complete || img.naturalWidth === 0) continue;
    const rect = img.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    const pixels = img.naturalWidth * img.naturalHeight;
    if (pixels <= 2000000) continue;
    out.push({
      src: (img.getAttribute("src") || "").slice(0, 200),
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight,
      pixels,
      box: {
        x: Math.round(rect.x), y: Math.round(rect.y),
        width: Math.round(rect.width), height: Math.round(rect.height),
      },
    });
  }
  return out;
}
"""

GENERIC_LINK_SCRIPT = """
() => {
  const out = [];
  const re = /^(click here|read more|learn more|see more|view more|find out more|here|this|more|details|start now|get started)$/i;
  const links = Array.from(document.querySelectorAll("a[href]"));
  for (const link of links) {
    if (out.length >= 5) break;
    const text = (link.innerText || "").trim().replace(/\\s+/g, " ");
    if (text.length < 2 || text.length > 40) continue;
    if (!re.test(text)) continue;
    out.push({
      text,
      href: (link.getAttribute("href") || "").slice(0, 120),
      box: (() => { const r = link.getBoundingClientRect(); return {
        x: Math.round(r.x), y: Math.round(r.y),
        width: Math.round(r.width), height: Math.round(r.height),
      }; })(),
    });
  }
  return out;
}
"""

EMPTY_LINK_SCRIPT = """
() => {
  const out = [];
  const links = Array.from(document.querySelectorAll("a[href]"));
  for (const link of links) {
    if (out.length >= 5) break;
    const text = (link.innerText || "").trim();
    const title = link.getAttribute("title") || "";
    const label = link.getAttribute("aria-label") || "";
    if (text || title || label) continue;
    if (link.querySelector("img, svg, i, span[class]")) continue;
    out.push({
      href: (link.getAttribute("href") || "").slice(0, 120),
      box: (() => { const r = link.getBoundingClientRect(); return {
        x: Math.round(r.x), y: Math.round(r.y),
        width: Math.round(r.width), height: Math.round(r.height),
      }; })(),
    });
  }
  return out;
}
"""

BLANK_TARGET_SCRIPT = """
() => {
  const out = [];
  const links = Array.from(document.querySelectorAll("a[href][target='_blank']"));
  for (const link of links) {
    if (out.length >= 5) break;
    const rel = (link.getAttribute("rel") || "").toLowerCase();
    if (rel.includes("noopener")) continue;
    out.push({
      text: (link.innerText || "").trim().replace(/\\s+/g, " ").slice(0, 60),
      href: (link.getAttribute("href") || "").slice(0, 120),
      rel: link.getAttribute("rel") || "",
    });
  }
  return out;
}
"""


def _finding(
    *,
    check: str,
    category: str,
    title: str,
    severity: str,
    viewport_width: int,
    description: str,
    selector: str = "",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "check": check,
        "category": category,
        "title": title,
        "severity": severity,
        "viewport_width": viewport_width,
        "description": description,
        "selector": selector,
        "evidence": evidence or {},
        "confidence": 1.0,
        "source": "deterministic",
    }


def _selector(element: dict[str, Any]) -> str:
    tag = element.get("tag", "")
    eid = element.get("id") or ""
    return f"{tag}{'#' + eid if eid else ''}"


def detect_tiny_text(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Flag visible body text rendered smaller than 12px."""
    try:
        elements = page.evaluate(TINY_TEXT_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate tiny-text script.")
        return []
    width = metrics["innerWidth"]
    findings: list[dict[str, Any]] = []
    for el in elements:
        findings.append(
            _finding(
                check="tiny_text",
                category="typography",
                title=f"Text smaller than 12px at {width}px",
                severity="medium",
                viewport_width=width,
                description=(
                    f"A {el['tag']} element renders body text at {el['fontSize']}, "
                    "which is too small to read comfortably."
                ),
                selector=_selector(el),
                evidence={"element": el},
            )
        )
    return findings


def detect_font_scale(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Flag pages with no coherent type scale (too many distinct font sizes)."""
    try:
        data = page.evaluate(FONT_SCALE_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate font-scale script.")
        return []
    count = int((data or {}).get("count", 0))
    if count <= 14:
        return []
    sizes = data.get("sizes", [])
    return [
        _finding(
            check="font_scale_inconsistency",
            category="typography",
            title=f"{count} distinct font sizes detected",
            severity="low",
            viewport_width=metrics["innerWidth"],
            description=(
                f"The page uses {count} distinct font sizes "
                f"({', '.join(str(s) + 'px' for s in sizes[:12])}"
                f"{'…' if len(sizes) > 12 else ''}), so the typography has no "
                "coherent scale."
            ),
            evidence={"distinct_sizes": sizes, "count": count},
        )
    ]


def detect_invisible_text(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Flag text whose computed color equals its background color."""
    try:
        elements = page.evaluate(INVISIBLE_TEXT_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate invisible-text script.")
        return []
    width = metrics["innerWidth"]
    findings: list[dict[str, Any]] = []
    for el in elements:
        findings.append(
            _finding(
                check="invisible_text",
                category="color",
                title=f"Invisible text at {width}px",
                severity="high",
                viewport_width=width,
                description=(
                    f"Text in a {el['tag']} element is rendered in the same "
                    f"color as its background ({el['color']} on "
                    f"{el['backgroundColor']}), making it invisible."
                ),
                selector=_selector(el),
                evidence={"element": el},
            )
        )
    return findings


def detect_overlapping_siblings(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Flag same-parent siblings whose boxes overlap by more than 8px."""
    try:
        pairs = page.evaluate(OVERLAPPING_SIBLINGS_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate overlapping-siblings script.")
        return []
    width = metrics["innerWidth"]
    findings: list[dict[str, Any]] = []
    for pair in pairs:
        a, b = pair["a"], pair["b"]
        overlap = pair["overlap"]
        findings.append(
            _finding(
                check="overlapping_siblings",
                category="spacing",
                title=f"Elements overlap at {width}px",
                severity="medium",
                viewport_width=width,
                description=(
                    f"Sibling elements {a['tag']} and {b['tag']} overlap by "
                    f"{overlap['x']}px horizontally and {overlap['y']}px "
                    "vertically inside their shared parent, which looks cramped "
                    "or broken."
                ),
                selector=_selector(a),
                evidence={"pair": pair},
            )
        )
    return findings


def detect_small_touch_targets(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Flag interactive targets smaller than the 44x44px touch guideline."""
    try:
        targets = page.evaluate(SMALL_TARGET_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate small-target script.")
        return []
    width = metrics["innerWidth"]
    findings: list[dict[str, Any]] = []
    for el in targets:
        box = el["box"]
        findings.append(
            _finding(
                check="small_touch_target",
                category="interaction",
                title=f"Small click target at {width}px",
                severity="medium",
                viewport_width=width,
                description=(
                    f"The {el['tag']} control is only {box['width']}x{box['height']}px; "
                    "targets smaller than 44x44px are hard to tap on touch screens."
                ),
                selector=_selector(el),
                evidence={"element": el},
            )
        )
    return findings


def detect_missing_pointer_cursor(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Flag buttons and links that do not show a pointer cursor."""
    try:
        targets = page.evaluate(POINTER_CURSOR_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate pointer-cursor script.")
        return []
    width = metrics["innerWidth"]
    findings: list[dict[str, Any]] = []
    for el in targets:
        findings.append(
            _finding(
                check="missing_pointer_cursor",
                category="interaction",
                title=f"Control does not show a pointer cursor at {width}px",
                severity="low",
                viewport_width=width,
                description=(
                    f"The {el['tag']} control is clickable but shows the default "
                    "arrow cursor instead of a pointer, so users may not realize "
                    "it is interactive."
                ),
                selector=_selector(el),
                evidence={"element": el},
            )
        )
    return findings


def detect_missing_image_dimensions(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Flag images without explicit width/height attributes (layout-shift risk)."""
    try:
        images = page.evaluate(IMAGE_DIMENSIONS_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate image-dimensions script.")
        return []
    width = metrics["innerWidth"]
    findings: list[dict[str, Any]] = []
    for img in images:
        findings.append(
            _finding(
                check="missing_image_dimensions",
                category="performance",
                title=f"Image without dimensions at {width}px",
                severity="low",
                viewport_width=width,
                description=(
                    "An image has no width/height attributes, so the browser "
                    "reserves no space for it and the layout can shift while it "
                    "loads."
                ),
                evidence={"image": img},
            )
        )
    return findings


def detect_oversized_images(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Flag rendered images whose intrinsic pixel area exceeds ~2 megapixels."""
    try:
        images = page.evaluate(OVERSIZED_IMAGE_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate oversized-image script.")
        return []
    width = metrics["innerWidth"]
    findings: list[dict[str, Any]] = []
    for img in images:
        findings.append(
            _finding(
                check="oversized_image",
                category="performance",
                title=f"Heavy image at {width}px",
                severity="low",
                viewport_width=width,
                description=(
                    f"An image is {img['naturalWidth']}x{img['naturalHeight']}px "
                    f"intrinsically (≈{img['pixels'] / 1_000_000:.1f} MP), far "
                    "larger than its display size — a heavy payload that slows "
                    "the page."
                ),
                evidence={"image": img},
            )
        )
    return findings


def detect_generic_link_text(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Flag vague link labels like 'click here' that hurt scanability."""
    try:
        links = page.evaluate(GENERIC_LINK_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate generic-link script.")
        return []
    width = metrics["innerWidth"]
    findings: list[dict[str, Any]] = []
    for link in links:
        findings.append(
            _finding(
                check="generic_link_text",
                category="ux",
                title=f"Vague link text at {width}px",
                severity="low",
                viewport_width=width,
                description=(
                    f"The link labeled {link['text']!r} gives no hint of its "
                    "destination; descriptive labels improve scanability and "
                    "screen-reader navigation."
                ),
                evidence={"link": link},
            )
        )
    return findings


def detect_empty_links(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Flag anchor tags with no accessible label at all."""
    try:
        links = page.evaluate(EMPTY_LINK_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate empty-link script.")
        return []
    width = metrics["innerWidth"]
    findings: list[dict[str, Any]] = []
    for link in links:
        findings.append(
            _finding(
                check="empty_link",
                category="ux",
                title=f"Link with no label at {width}px",
                severity="medium",
                viewport_width=width,
                description=(
                    "An anchor has no text, title or aria-label, so users cannot "
                    "tell what it points to."
                ),
                evidence={"link": link},
            )
        )
    return findings


def detect_blank_target_without_rel(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Flag target=_blank links missing rel=noopener."""
    try:
        links = page.evaluate(BLANK_TARGET_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not evaluate blank-target script.")
        return []
    width = metrics["innerWidth"]
    findings: list[dict[str, Any]] = []
    for link in links:
        findings.append(
            _finding(
                check="blank_target_without_rel",
                category="ux",
                title=f"New-tab link without rel=noopener at {width}px",
                severity="low",
                viewport_width=width,
                description=(
                    "A link opens in a new tab without rel=noopener, which can "
                    "let the new page tamper with this one."
                ),
                evidence={"link": link},
            )
        )
    return findings


def detect_visual(page: Page, metrics: dict[str, int]) -> list[dict[str, Any]]:
    """Run every deterministic visual-design detector and return all findings."""
    findings: list[dict[str, Any]] = []
    findings.extend(detect_tiny_text(page, metrics))
    findings.extend(detect_font_scale(page, metrics))
    findings.extend(detect_invisible_text(page, metrics))
    findings.extend(detect_overlapping_siblings(page, metrics))
    findings.extend(detect_small_touch_targets(page, metrics))
    findings.extend(detect_missing_pointer_cursor(page, metrics))
    findings.extend(detect_missing_image_dimensions(page, metrics))
    findings.extend(detect_oversized_images(page, metrics))
    findings.extend(detect_generic_link_text(page, metrics))
    findings.extend(detect_empty_links(page, metrics))
    findings.extend(detect_blank_target_without_rel(page, metrics))
    return findings
