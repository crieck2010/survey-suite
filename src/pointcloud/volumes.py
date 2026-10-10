"""Cut/fill volumes by the grid (borrow-pit) method.

Volume = sum over cells of (surface - reference) * cell_area, split into
cut (positive) and fill (negative) components. This is the standard
earthwork computation: compare a surface grid against a design/base
elevation, or two surface grids against each other (e.g. pre- vs.
post-construction DEMs from ``dem.grid_minimum``).
"""
from __future__ import annotations

import math
from typing import Sequence

Grid = Sequence[Sequence[float]]


def _is_nodata(v: float, nodata: float) -> bool:
    if isinstance(nodata, float) and math.isnan(nodata):
        return isinstance(v, float) and math.isnan(v)
    return v == nodata


def _check_grids(a: Grid, b: Grid | None = None) -> tuple[int, int]:
    h = len(a)
    if h == 0 or any(len(row) != len(a[0]) for row in a):
        raise ValueError("Grid must be non-empty and rectangular")
    if b is not None:
        if len(b) != h or any(len(r) != len(a[0]) for r in b):
            raise ValueError("Grid shapes differ")
    return h, len(a[0])


def volume_grid(grid: Grid, base_elevation: float, cell_area: float,
                nodata: float = float("nan")) -> tuple[float, float, float]:
    """Cut/fill of a surface against a flat base elevation.

    Returns (cut, fill, net) volumes; net = cut - fill. Nodata cells are
    skipped.
    """
    h, w = _check_grids(grid)
    if cell_area <= 0:
        raise ValueError("cell_area must be positive")
    cut = fill = 0.0
    for i in range(h):
        for j in range(w):
            v = grid[i][j]
            if _is_nodata(v, nodata):
                continue
            d = (v - base_elevation) * cell_area
            if d > 0:
                cut += d
            elif d < 0:
                fill -= d
    return cut, fill, cut - fill


def volume_between(upper: Grid, lower: Grid, cell_area: float,
                   nodata: float = float("nan")) -> tuple[float, float, float]:
    """Cut/fill between two co-registered surface grids.

    Returns (cut, fill, net) where cut is the volume by which ``upper``
    exceeds ``lower``. Cells where either grid is nodata are skipped.
    """
    h, w = _check_grids(upper, lower)
    if cell_area <= 0:
        raise ValueError("cell_area must be positive")
    cut = fill = 0.0
    for i in range(h):
        for j in range(w):
            vu, vl = upper[i][j], lower[i][j]
            if _is_nodata(vu, nodata) or _is_nodata(vl, nodata):
                continue
            d = (vu - vl) * cell_area
            if d > 0:
                cut += d
            elif d < 0:
                fill -= d
    return cut, fill, cut - fill
