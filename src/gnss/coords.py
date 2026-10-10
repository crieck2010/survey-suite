"""WGS84 coordinate conversion and baseline vectors.

Self-contained (no dependency on survey-geodesy) so this engine stays
independently pip-installable; the math is the same standard WGS84
formulation, so results agree with survey-geodesy's converters to
millimetre level.

Interoperability: decimal-degree / ECEF outputs feed survey-geodesy for
datum shifts and projections, and session mean positions feed
survey-cogo as traverse control.
"""
from __future__ import annotations

import math

# WGS84 ellipsoid
A = 6378137.0
F = 1 / 298.257223563
E2 = 2 * F - F * F


def geodetic_to_ecef(lat: float, lon: float, h: float = 0.0
                     ) -> tuple[float, float, float]:
    """Decimal degrees + ellipsoidal height -> ECEF metres (WGS84)."""
    lat_r, lon_r = math.radians(lat), math.radians(lon)
    sin_lat, cos_lat = math.sin(lat_r), math.cos(lat_r)
    n = A / math.sqrt(1 - E2 * sin_lat * sin_lat)
    x = (n + h) * cos_lat * math.cos(lon_r)
    y = (n + h) * cos_lat * math.sin(lon_r)
    z = (n * (1 - E2) + h) * sin_lat
    return (x, y, z)


def ecef_to_geodetic(x: float, y: float, z: float
                     ) -> tuple[float, float, float]:
    """ECEF metres -> (lat, lon, h) via iterative solution (mm-level)."""
    lon = math.degrees(math.atan2(y, x))
    p = math.hypot(x, y)
    lat = math.degrees(math.atan2(z, p * (1 - E2)))  # first approximation
    for _ in range(10):
        lat_r = math.radians(lat)
        sin_lat = math.sin(lat_r)
        n = A / math.sqrt(1 - E2 * sin_lat * sin_lat)
        h = p / math.cos(lat_r) - n
        lat_new = math.degrees(math.atan2(z, p * (1 - E2 * n / (n + h))))
        if abs(lat_new - lat) < 1e-12:
            lat = lat_new
            break
        lat = lat_new
    lat_r = math.radians(lat)
    n = A / math.sqrt(1 - E2 * math.sin(lat_r) ** 2)
    h = p / math.cos(lat_r) - n
    return (lat, lon, h)


def baseline(ecef1: tuple[float, float, float],
             ecef2: tuple[float, float, float]
             ) -> tuple[tuple[float, float, float], float]:
    """Baseline vector (dx, dy, dz) in metres and its length, ECEF frame."""
    d = (ecef2[0] - ecef1[0], ecef2[1] - ecef1[1], ecef2[2] - ecef1[2])
    return d, math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)


def unit_vectors_to_enu(lat: float, lon: float,
                        sat_ecef_dirs: list[tuple[float, float, float]]
                        ) -> list[tuple[float, float, float]]:
    """Rotate ECEF line-of-sight unit vectors into the local ENU frame.

    DOP's horizontal/vertical split is only meaningful in a local frame,
    so geometry given in ECEF should pass through here first.
    """
    lat_r, lon_r = math.radians(lat), math.radians(lon)
    sl, cl = math.sin(lat_r), math.cos(lat_r)
    so, co = math.sin(lon_r), math.cos(lon_r)
    out = []
    for dx, dy, dz in sat_ecef_dirs:
        e = -so * dx + co * dy
        n = -sl * co * dx - sl * so * dy + cl * dz
        u = cl * co * dx + cl * so * dy + sl * dz
        out.append((e, n, u))
    return out
