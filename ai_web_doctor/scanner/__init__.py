"""scanner package.

Playwright-based website scanning services for AI Web Doctor.

Modules:

* ``security.py``    — URL validation and SSRF protection.
* ``browser.py``     — Playwright browser/session management.
* ``dom.py``         — In-browser DOM metrics and lightweight DOM snapshots.
* ``responsive.py``  — Deterministic responsive-layout checks.
* ``screenshots.py`` — Screenshot capture.
* ``analyzer.py``    — Orchestrates a full scan of a single URL/viewport.
"""

from __future__ import annotations

__all__: list[str] = []
