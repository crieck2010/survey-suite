"""Forward computation: locate a point from a known point, azimuth, and distance."""
from __future__ import annotations

import math

from .point import Point


def forward(start: Point, azimuth_deg: float, distance: float, name: str = "") -> Point:
    """Compute the point at ``distance`` from ``start`` along ``azimuth_deg``.

    dN = distance * cos(az), dE = distance * sin(az).
    """
    az = math.radians(azimuth_deg)
    return Point(
        northing=start.northing + distance * math.cos(az),
        easting=start.easting + distance * math.sin(az),
        name=name or start.name,
        elevation=start.elevation,
    )
