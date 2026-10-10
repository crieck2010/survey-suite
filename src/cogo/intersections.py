"""Intersection computations: bearing-bearing and distance-distance."""
from __future__ import annotations

import math

from .point import Point

_EPS = 1e-12


def bearing_bearing(p1: Point, azimuth1: float, p2: Point, azimuth2: float,
                    name: str = "") -> Point:
    """Intersect two rays defined by (point, azimuth) pairs.

    Solves p1 + t*d1 = p2 + s*d2 where d = (sin az, cos az) in (E, N).
    Raises ValueError if the rays are parallel (or nearly so).
    """
    a1, a2 = math.radians(azimuth1), math.radians(azimuth2)
    # 2x2 system: [sin a1, -sin a2; cos a1, -cos a2] [t, s]^T = [dE, dN]
    det = math.sin(a2 - a1)  # = -sin a1 cos a2 + cos a1 sin a2
    if abs(det) < _EPS:
        raise ValueError("Rays are parallel; no unique intersection")
    d_e = p2.easting - p1.easting
    d_n = p2.northing - p1.northing
    t = (-d_e * math.cos(a2) + math.sin(a2) * d_n) / det
    return Point(
        northing=p1.northing + t * math.cos(a1),
        easting=p1.easting + t * math.sin(a1),
        name=name,
        elevation=(p1.elevation + p2.elevation) / 2.0,
    )


def distance_distance(p1: Point, radius1: float, p2: Point, radius2: float,
                      name: str = "") -> tuple[Point, Point]:
    """Intersect two circles; returns both intersection points.

    Raises ValueError if the circles do not intersect (separate, one inside
    the other, or concentric).
    """
    d_e = p2.easting - p1.easting
    d_n = p2.northing - p1.northing
    d = math.hypot(d_e, d_n)
    if d < _EPS:
        raise ValueError("Circle centers are coincident")
    if d > radius1 + radius2 + _EPS:
        raise ValueError("Circles are separate; no intersection")
    if d < abs(radius1 - radius2) - _EPS:
        raise ValueError("One circle lies inside the other; no intersection")

    a = (radius1 ** 2 - radius2 ** 2 + d ** 2) / (2.0 * d)
    h_sq = radius1 ** 2 - a ** 2
    h = math.sqrt(max(h_sq, 0.0))

    # Base point along p1 -> p2 at distance a from p1
    base_e = p1.easting + a * d_e / d
    base_n = p1.northing + a * d_n / d
    # Perpendicular offset (both directions)
    off_e = -h * d_n / d
    off_n = h * d_e / d
    elev = (p1.elevation + p2.elevation) / 2.0
    return (
        Point(northing=base_n + off_n, easting=base_e + off_e, name=name, elevation=elev),
        Point(northing=base_n - off_n, easting=base_e - off_e, name=name, elevation=elev),
    )
