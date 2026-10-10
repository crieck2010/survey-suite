"""Angle utilities for surveying computations.

Conventions used throughout this package:
  - Plane angles are decimal degrees unless stated otherwise.
  - Azimuths are measured clockwise from north, normalized to [0, 360).
  - Bearings are quadrant strings like ``N 45°30'00" E``.
"""
from __future__ import annotations

import math
import re

_DMS_RE = re.compile(
    r"""^\s*(?P<sign>[+-])?\s*
        (?P<d>\d+(?:\.\d+)?)\s*[°d]\s*
        (?:(?P<m>\d+(?:\.\d+)?)\s*['\u2032])?\s*
        (?:(?P<s>\d+(?:\.\d+)?)\s*["\u2033])?\s*$""",
    re.VERBOSE,
)

_BEARING_RE = re.compile(r"^\s*([NS])\s*(.+?)\s*([EW])\s*$", re.IGNORECASE)


def dms_to_decimal(degrees: float, minutes: float = 0.0, seconds: float = 0.0) -> float:
    """Convert degrees/minutes/seconds to decimal degrees.

    A negative sign on any component makes the result negative.
    """
    sign = -1.0 if (degrees < 0 or minutes < 0 or seconds < 0) else 1.0
    return sign * (abs(degrees) + abs(minutes) / 60.0 + abs(seconds) / 3600.0)


def parse_dms(text: str) -> float:
    """Parse a DMS string like ``122°30'15"`` to decimal degrees."""
    m = _DMS_RE.match(text)
    if not m:
        raise ValueError(f"Cannot parse DMS angle: {text!r}")
    sign = -1.0 if m.group("sign") == "-" else 1.0
    d = float(m.group("d"))
    minutes = float(m.group("m")) if m.group("m") else 0.0
    seconds = float(m.group("s")) if m.group("s") else 0.0
    return sign * (d + minutes / 60.0 + seconds / 3600.0)


def decimal_to_dms(decimal: float) -> tuple[int, int, float]:
    """Convert decimal degrees to a (degrees, minutes, seconds) tuple.

    The sign is carried on the degrees component.
    """
    sign = -1 if decimal < 0 else 1
    remainder = abs(decimal)
    d = int(remainder)
    remainder = (remainder - d) * 60.0
    m = int(remainder)
    s = (remainder - m) * 60.0
    # Guard against 59.9999999 -> 60.0 rounding edge
    if s >= 59.99995:
        s = 0.0
        m += 1
    if m >= 60:
        m = 0
        d += 1
    return sign * d, m, s


def format_dms(decimal: float, ndp: int = 1) -> str:
    """Format decimal degrees as a DMS string, e.g. ``122°30'15.0"``."""
    d, m, s = decimal_to_dms(decimal)
    return f"{abs(d)}°{m:02d}'{s:0{3 + ndp}.{ndp}f}\""


def normalize_angle(angle: float) -> float:
    """Normalize any angle to [0, 360)."""
    return angle % 360.0


def azimuth_to_bearing(azimuth: float) -> str:
    """Convert an azimuth (clockwise from north) to a quadrant bearing string."""
    az = normalize_angle(azimuth)
    if az < 90.0:
        return f"N {format_dms(az)} E"
    if az < 180.0:
        return f"S {format_dms(180.0 - az)} E"
    if az < 270.0:
        return f"S {format_dms(az - 180.0)} W"
    return f"N {format_dms(360.0 - az)} W"


def bearing_to_azimuth(bearing: str) -> float:
    """Convert a quadrant bearing string like ``S 30°15'00" W`` to an azimuth."""
    m = _BEARING_RE.match(bearing)
    if not m:
        raise ValueError(f"Cannot parse bearing: {bearing!r}")
    ns, dms_text, ew = m.group(1).upper(), m.group(2), m.group(3).upper()
    d = parse_dms(dms_text)
    if ns == "N" and ew == "E":
        return normalize_angle(d)
    if ns == "S" and ew == "E":
        return normalize_angle(180.0 - d)
    if ns == "S" and ew == "W":
        return normalize_angle(180.0 + d)
    return normalize_angle(360.0 - d)


def radians_to_dms_string(radians: float) -> str:
    """Convenience: radians -> formatted DMS string."""
    return format_dms(math.degrees(radians))
