"""Ground classification by grid-minimum morphological filtering.

Method: bin points into a regular grid, take the minimum z per cell as the
local ground estimate, and classify points within ``threshold`` above that
minimum as ground (ASPRS class 2 by default). Two passes, O(n), no spatial
index required.

This is a first-order filter suited to gentle terrain. Steep terrain,
dense low vegetation, and bridges need progressive morphological or
surface-based filters (roadmap).
"""
from __future__ import annotations

import math
from typing import Sequence

from .point import GROUND, Point, as_point, xyz


def classify_ground_grid(points: Sequence, cell_size: float, threshold: float,
                         ground_class: int = GROUND) -> list[Point]:
    """Classify ground points in a copy of the point sequence.

    Args:
        points: Point-likes to classify.
        cell_size: Grid cell size (same unit as x/y). Smaller cells follow
            terrain better but need enough points per cell.
        threshold: Points within this height above their cell minimum are
            labelled ground.
        ground_class: Classification code assigned to ground points.

    Returns a new list of :class:`Point`; non-ground points keep their
    original classification.
    """
    if cell_size <= 0:
        raise ValueError("cell_size must be positive")
    if threshold < 0:
        raise ValueError("threshold cannot be negative")
    pts = [as_point(p) for p in points]
    if not pts:
        return []

    # Pass 1: per-cell minimum z.
    minima: dict[tuple[int, int], float] = {}
    keys: list[tuple[int, int]] = []
    for p in pts:
        key = (math.floor(p.x / cell_size), math.floor(p.y / cell_size))
        keys.append(key)
        if key not in minima or p.z < minima[key]:
            minima[key] = p.z

    # Pass 2: label points near their cell minimum as ground.
    out: list[Point] = []
    for p, key in zip(pts, keys):
        if p.z - minima[key] <= threshold:
            out.append(Point(p.x, p.y, p.z, intensity=p.intensity,
                             classification=ground_class,
                             return_number=p.return_number,
                             number_of_returns=p.number_of_returns))
        else:
            out.append(p)
    return out
