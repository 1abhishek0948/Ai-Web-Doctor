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
import threading

import django


def _start_watchdog() -> None:
    """Kill this process hard if the scan exceeds its deadline.

    Playwright sync calls can hang forever when a renderer wedges (e.g. heavy
    pages under memory pressure); a wedged call never returns, so no in-process
    timeout can interrupt it. ``os._exit`` from a daemon thread is the only
    guarantee — the parent web process and the stale-scan sweeper then mark
    the scan failed instead of the container dying of memory exhaustion.
    """
    deadline_s = int(
        os.environ.get("SCAN_MAX_DURATION_SECONDS") or os.environ.get("MAX_SCAN_DURATION") or 300
    )
    buffer_s = 120
    timer = threading.Timer(deadline_s + buffer_s, os._exit, args=(1,))
    timer.daemon = True
    timer.start()


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

    _start_watchdog()
    execute_scan(scan_id)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    raise SystemExit(main())