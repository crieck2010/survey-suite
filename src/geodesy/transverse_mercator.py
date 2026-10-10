"""Transverse Mercator projection (Snyder/Redfearn series).

Forward:  (lat, lon) -> (easting, northing)
Inverse:  (easting, northing) -> (lat, lon)

Accurate to millimetres within a few degrees of the central meridian --
the normal operating range for UTM and State Plane (TM) zones.
"""
from __future__ import annotations

import math

from .ellipsoids import Ellipsoid, WGS84


def _meridian_arc(phi: float, ell: Ellipsoid) -> float:
    e2, e4, e6 = ell.e2, ell.e2 ** 2, ell.e2 ** 3
    return ell.a * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
        - (35 * e6 / 3072) * math.sin(6 * phi)
    )


def tm_forward(lat_deg: float, lon_deg: float, lon0_deg: float,
               k0: float = 1.0, false_easting: float = 0.0,
               false_northing: float = 0.0,
               ellipsoid: Ellipsoid = WGS84) -> tuple[float, float]:
    """Project (lat, lon) to (easting, northing)."""
    phi = math.radians(lat_deg)
    lam = math.radians(lon_deg)
    lam0 = math.radians(lon0_deg)
    n = ellipsoid.a / math.sqrt(1 - ellipsoid.e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = ellipsoid.ep2 * math.cos(phi) ** 2
    a_ = (lam - lam0) * math.cos(phi)
    m = _meridian_arc(phi, ellipsoid)

    easting = false_easting + k0 * n * (
        a_ + (1 - t + c) * a_ ** 3 / 6
        + (5 - 18 * t + t ** 2 + 72 * c - 58 * ellipsoid.ep2) * a_ ** 5 / 120
    )
    northing = false_northing + k0 * (
        m + n * math.tan(phi) * (
            a_ ** 2 / 2
            + (5 - t + 9 * c + 4 * c ** 2) * a_ ** 4 / 24
            + (61 - 58 * t + t ** 2 + 600 * c - 330 * ellipsoid.ep2) * a_ ** 6 / 720
        )
    )
    return easting, northing


def tm_inverse(easting: float, northing: float, lon0_deg: float,
               k0: float = 1.0, false_easting: float = 0.0,
               false_northing: float = 0.0,
               ellipsoid: Ellipsoid = WGS84) -> tuple[float, float]:
    """Unproject (easting, northing) to (lat_deg, lon_deg)."""
    e2, e4, e6 = ellipsoid.e2, ellipsoid.e2 ** 2, ellipsoid.e2 ** 3
    m = (northing - false_northing) / k0
    mu = m / (ellipsoid.a * (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))

    n1 = ellipsoid.a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    t1 = math.tan(phi1) ** 2
    c1 = ellipsoid.ep2 * math.cos(phi1) ** 2
    r1 = ellipsoid.a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = (easting - false_easting) / (n1 * k0)

    phi = phi1 - (n1 * math.tan(phi1) / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ellipsoid.ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ellipsoid.ep2
           - 3 * c1 ** 2) * d ** 6 / 720
    )
    lam = (d - (1 + 2 * t1 + c1) * d ** 3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ellipsoid.ep2
              + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(phi1)

    return math.degrees(phi), math.degrees(lam) + lon0_deg
