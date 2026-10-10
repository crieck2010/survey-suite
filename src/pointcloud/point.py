"""Point model and ASPRS classification codes.

Interoperability: classification codes follow the ASPRS LAS standard so
classified clouds round-trip with real LiDAR tooling (laspy, PDAL).
Point-like data is duck-typed -- tuples, lists, numpy rows, and ``Point``
all work wherever points are consumed -- so numpy structured arrays and
laspy point records need no adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# ASPRS LAS classification codes (abridged to the commonly used set).
CREATED = 0
UNCLASSIFIED = 1
GROUND = 2
LOW_VEGETATION = 3
MEDIUM_VEGETATION = 4
HIGH_VEGETATION = 5
BUILDING = 6
NOISE = 7
WATER = 9
BRIDGE_DECK = 17

CLASSIFICATION_NAMES: dict[int, str] = {
    CREATED: "created",
    UNCLASSIFIED: "unclassified",
    GROUND: "ground",
    LOW_VEGETATION: "low_vegetation",
    MEDIUM_VEGETATION: "medium_vegetation",
    HIGH_VEGETATION: "high_vegetation",
    BUILDING: "building",
    NOISE: "noise",
    WATER: "water",
    BRIDGE_DECK: "bridge_deck",
}

PointLike = Sequence[float]  # anything with [x, y, z, ...]


@dataclass
class Point:
    """A single LiDAR-style point."""

    x: float
    y: float
    z: float
    intensity: float = 0.0
    classification: int = UNCLASSIFIED
    return_number: int = 1
    number_of_returns: int = 1

    def xyz(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


def xyz(p) -> tuple[float, float, float]:
    """Extract (x, y, z) from any point-like: Point, tuple, numpy row, ..."""
    if isinstance(p, Point):
        return p.xyz()
    if hasattr(p, "x") and hasattr(p, "y") and hasattr(p, "z"):
        return (float(p.x), float(p.y), float(p.z))
    return (float(p[0]), float(p[1]), float(p[2]))


def as_point(p) -> Point:
    """Coerce a point-like to a canonical ``Point`` (extra fields default)."""
    if isinstance(p, Point):
        return p
    x, y, z = xyz(p)
    try:
        intensity = float(p[3])
    except (IndexError, TypeError):
        intensity = 0.0
    try:
        classification = int(p[4])
    except (IndexError, TypeError):
        classification = UNCLASSIFIED
    return Point(x, y, z, intensity=intensity, classification=classification)
