"""Update-check hook (stubbed, non-blocking).

The desktop app may call :func:`check_for_updates` on startup in a
background thread. It fetches a plain-text version file from
``UPDATE_URL`` (set this to the real published URL at release time),
compares against the running version, and reports availability.

Never raises and never blocks the UI: short timeout, all exceptions
swallowed into ``(False, None)``.
"""
from __future__ import annotations

import urllib.request

UPDATE_URL = "https://example.com/survey-suite/latest-version.txt"
TIMEOUT_S = 3


def _parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in text.strip().split(".") if p.isdigit())


def check_for_updates(current_version: str,
                      url: str = UPDATE_URL) -> tuple[bool, str | None]:
    """Return ``(update_available, latest_version)``; never raises."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
            latest = resp.read().decode("utf-8", "replace").strip()
        if not latest:
            return (False, None)
        available = _parse_version(latest) > _parse_version(current_version)
        return (available, latest)
    except Exception:  # noqa: BLE001 -- update checks must never crash
        return (False, None)
