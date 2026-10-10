"""Inverse computation: azimuth and distance between two known points."""
from __future__ import annotations

import math
from typing import NamedTuple

from .angles import normalize_angle
from .point import Point


class Inverse(NamedTuple):
    """Result of an inverse: azimuth (deg, clockwise from north) and distance."""

    azimuth: float
    distance: float


def inverse(from_point: Point, to_point: Point) -> Inverse:
    """Compute the azimuth and horizontal distance from one point to another.

    Azimuth = atan2(dE, dN) normalized to [0, 360).
    """
    d_northing = to_point.northing - from_point.northing
    d_easting = to_point.easting - from_point.easting
    distance = math.hypot(d_easting, d_northing)
    if distance == 0.0:
        raise ValueError("Inverse is undefined for coincident points")
    azimuth = normalize_angle(math.degrees(math.atan2(d_easting, d_northing)))
    return Inverse(azimuth=azimuth, distance=distance)
