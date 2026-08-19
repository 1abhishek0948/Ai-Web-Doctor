"""Subprocess scan runner (``python -m scanner.run <scan_id>``).

Used when ``SCAN_SUBPROCESS_MODE`` is enabled (production): the web process
spawns a short-lived child that executes the scan with Chromium and exits.
All browser memory is released when the child exits, and a Chromium crash/OOM
in the child can never take down the web process.

The child inherits the parent environment (DATABASE_URL, SECRET_KEY,
DJANGO_SETTINGS_MODULE, ...) so no extra configuration is needed. Status
updates go to Postgres, which the UI already polls.
"""

from __future__ import annotations

import os
import sys

import django


def main() -> int:
    django.setup()

    from apps.scans.services import execute_scan

    if len(sys.argv) != 2:
        print("usage: python -m scanner.run <scan_id>", file=sys.stderr)
        return 2

    try:
        scan_id = int(sys.argv[1])
    except ValueError:
        print("scan_id must be an integer", file=sys.stderr)
        return 2

    execute_scan(scan_id)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    raise SystemExit(main())