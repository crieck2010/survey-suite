"""Polygon area (coordinate method) and perimeter."""
from __future__ import annotations

import math

from .point import Point


def polygon_area(points: list[Point]) -> float:
    """Area of a polygon by the coordinate (shoelace) method.

    Points should be ordered around the polygon (either direction); the
    polygon is closed implicitly. Returns the absolute area.
    """
    if len(points) < 3:
        raise ValueError("A polygon needs at least 3 points")
    total = 0.0
    n = len(points)
    for i in range(n):
        j = (i + 1) % n
        total += points[i].easting * points[j].northing
        total -= points[j].easting * points[i].northing
    return abs(total) / 2.0


def polygon_perimeter(points: list[Point]) -> float:
    """Perimeter length of a polygon (closed implicitly)."""
    if len(points) < 2:
        raise ValueError("Need at least 2 points")
    total = 0.0
    n = len(points)
    for i in range(n):
        j = (i + 1) % n
        total += math.hypot(points[j].easting - points[i].easting,
                            points[j].northing - points[i].northing)
    return total
