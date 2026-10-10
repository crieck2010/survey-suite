"""Geodetic (lat/lon/h) <-> ECEF (X/Y/Z) conversions."""
from __future__ import annotations

import math

from .ellipsoids import Ellipsoid, WGS84


def geodetic_to_ecef(lat_deg: float, lon_deg: float, h: float,
                     ellipsoid: Ellipsoid = WGS84) -> tuple[float, float, float]:
    """Convert geodetic coordinates to Earth-centred Earth-fixed XYZ (metres)."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    n = ellipsoid.a / math.sqrt(1.0 - ellipsoid.e2 * math.sin(lat) ** 2)
    x = (n + h) * math.cos(lat) * math.cos(lon)
    y = (n + h) * math.cos(lat) * math.sin(lon)
    z = (n * (1.0 - ellipsoid.e2) + h) * math.sin(lat)
    return x, y, z


def ecef_to_geodetic(x: float, y: float, z: float,
                     ellipsoid: Ellipsoid = WGS84) -> tuple[float, float, float]:
    """Convert ECEF XYZ (metres) to (lat_deg, lon_deg, h). Iterative, ~1e-12 rad."""
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1.0 - ellipsoid.e2))  # initial guess
    for _ in range(20):
        n = ellipsoid.a / math.sqrt(1.0 - ellipsoid.e2 * math.sin(lat) ** 2)
        h = p / math.cos(lat) - n
        lat_new = math.atan2(z, p * (1.0 - ellipsoid.e2 * n / (n + h)))
        if abs(lat_new - lat) < 1e-13:
            lat = lat_new
            break
        lat = lat_new
    n = ellipsoid.a / math.sqrt(1.0 - ellipsoid.e2 * math.sin(lat) ** 2)
    h = p / math.cos(lat) - n
    return math.degrees(lat), math.degrees(lon), h
