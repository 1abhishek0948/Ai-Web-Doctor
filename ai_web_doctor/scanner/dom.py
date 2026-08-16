"""In-browser DOM collection.

Everything here runs inside the target page via ``page.evaluate`` so the
measurements reflect what the browser actually computed after JavaScript
executed — never guesses.

For Part 2 we collect exact layout metrics (window / document / scroll
dimensions) and a deliberately small DOM snapshot for future evidence.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

# Returns exact layout metrics. Values are plain numbers.
METRICS_SCRIPT = """
() => {
  const doc = document.documentElement;
  const body = document.body;
  const scrollW = Math.max(
    body ? body.scrollWidth : 0, doc.scrollWidth, doc.clientWidth
  );
  const scrollH = Math.max(
    body ? body.scrollHeight : 0, doc.scrollHeight, doc.clientHeight
  );
  return {
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    outerWidth: window.outerWidth,
    outerHeight: window.outerHeight,
    scrollWidth: scrollW,
    scrollHeight: scrollH,
    documentWidth: doc.clientWidth,
    documentHeight: doc.clientHeight,
    clientWidth: doc.clientWidth,
    clientHeight: doc.clientHeight,
  };
}
"""

PAGE_INFO_SCRIPT = """
() => ({
  title: document.title || "",
  lang: document.documentElement.getAttribute("lang") || "",
})
"""


def collect_page_info(page: Page) -> dict[str, str]:
    """Return the page title and language attribute."""
    try:
        return page.evaluate(PAGE_INFO_SCRIPT)
    except Exception:  # noqa: BLE001
        logger.warning("Could not collect page info; falling back to URL title.")
        return {"title": "", "lang": ""}


def collect_metrics(page: Page) -> dict[str, int]:
    """Collect exact layout metrics from the live page."""
    return page.evaluate(METRICS_SCRIPT)


def collect_dom_snapshot(page: Page, limit: int = 150) -> list[dict[str, Any]]:
    """Return a compact representation of visible, meaningful elements.

    The snapshot intentionally excludes text content of large containers and
    only inspects elements with non-trivial bounding boxes. ``limit`` caps the
    number of elements so huge pages don't bloat memory or future AI requests.
    """
    script = f"""
    () => {{
      const limit = {int(limit)};
      const out = [];
      const seen = new Set();
      const walker = document.createTreeWalker(
        document.body, NodeFilter.SHOW_ELEMENT
      );
      let el;
      while ((el = walker.nextNode()) && out.length < limit) {{
        const rect = el.getBoundingClientRect();
        if (rect.width < 2 || rect.height < 2) continue;
        if (rect.bottom < 0 || rect.right < 0) continue;
        const style = window.getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden") continue;
        if (seen.has(el.tagName + ":" + el.className)) continue;
        seen.add(el.tagName + ":" + el.className);
        const text = (el.innerText || "").trim().replace(/\\s+/g, " ").slice(0, 120);
        out.push({{
          tag: el.tagName.toLowerCase(),
          id: el.id || "",
          classes: String(el.className || "").split(/\\s+/).filter(Boolean).slice(0, 8),
          text,
          box: {{
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          }},
          display: style.display,
          position: style.position,
          fontSize: style.fontSize,
          fontWeight: style.fontWeight,
          color: style.color,
          backgroundColor: style.backgroundColor,
          margin: style.margin,
          padding: style.padding,
          overflowX: style.overflowX,
          zIndex: style.zIndex,
        }});
      }}
      return out;
    }}
    """
    try:
        return page.evaluate(script)
    except Exception:  # noqa: BLE001
        logger.warning("Could not collect DOM snapshot for page.")
        return []
