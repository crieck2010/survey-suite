"""License-key hook (stubbed, non-blocking).

Monetization readiness: the desktop app calls :func:`check_license` at
startup, but enforcement is OFF -- the app always runs. When the product
is ready to sell, replace :func:`_verify_key` with a real check (local
signed key or a Gumroad / Lemon Squeezy license API call) and flip
``REQUIRE_LICENSE``.

Never raises: any I/O or verification failure degrades to
``LicenseStatus(tier="none", valid=False)`` so a licensing outage can
never brick the app.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

REQUIRE_LICENSE = False
LICENSE_ENV_VAR = "SURVEY_SUITE_LICENSE"
LICENSE_FILE = os.path.join(os.path.expanduser("~"), ".survey-suite",
                            "license.key")


@dataclass(frozen=True)
class LicenseStatus:
    valid: bool
    tier: str          # "none", "beta", "pro", ...
    message: str


def _read_key() -> str | None:
    key = os.environ.get(LICENSE_ENV_VAR)
    if key:
        return key.strip()
    try:
        with open(LICENSE_FILE, encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def _verify_key(key: str) -> LicenseStatus:
    # STUB: accept any non-empty key as a beta license. Replace with real
    # verification (e.g. Ed25519-signed payload, or a merchant-of-record
    # license API) before enforcing.
    if key and len(key) >= 8:
        return LicenseStatus(valid=True, tier="beta",
                             message="Beta license accepted (stub check).")
    return LicenseStatus(valid=False, tier="none",
                         message="License key not recognized.")


def check_license() -> LicenseStatus:
    """Return the current license status; never raises."""
    try:
        key = _read_key()
        if not key:
            return LicenseStatus(valid=False, tier="none",
                                 message="No license key found; "
                                         "running unlicensed.")
        return _verify_key(key)
    except Exception as exc:  # noqa: BLE001 -- licensing must never crash
        return LicenseStatus(valid=False, tier="none",
                             message=f"License check failed: {exc}")


def license_required() -> bool:
    """Whether the app should refuse to run without a valid license."""
    return REQUIRE_LICENSE
