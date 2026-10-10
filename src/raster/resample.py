"""Resampling between grid dimensions.

Nearest-neighbour (categorical-safe) and bilinear (continuous) methods.
Nodata neighbours are skipped with renormalized weights in bilinear mode;
a pixel whose whole support is nodata stays nodata.
"""
from __future__ import annotations

import math

from .raster import Grid, grid_shape, is_nodata


def resample(grid: Grid, new_width: int, new_height: int,
             method: str = "nearest",
             nodata: float | None = None) -> list[list[float]]:
    """Resample a grid to (new_height, new_width)."""
    if new_width <= 0 or new_height <= 0:
        raise ValueError("Target dimensions must be positive")
    if method not in ("nearest", "bilinear"):
        raise ValueError("method must be 'nearest' or 'bilinear'")
    src_h, src_w = grid_shape(grid)
    out_nd = float("nan") if nodata is None else nodata
    out: list[list[float]] = []
    for r in range(new_height):
        row_out: list[float] = []
        for c in range(new_width):
            # Map destination pixel centre into source pixel coordinates.
            src_y = (r + 0.5) * src_h / new_height - 0.5
            src_x = (c + 0.5) * src_w / new_width - 0.5
            if method == "nearest":
                sy = min(max(int(round(src_y)), 0), src_h - 1)
                sx = min(max(int(round(src_x)), 0), src_w - 1)
                row_out.append(grid[sy][sx])
            else:
                row_out.append(_bilinear(grid, src_x, src_y, src_w, src_h,
                                        nodata, out_nd))
        out.append(row_out)
    return out


def _bilinear(grid: Grid, x: float, y: float, src_w: int, src_h: int,
              nodata: float | None, out_nd: float) -> float:
    x0 = int(math.floor(x))
    y0 = int(math.floor(y))
    fx, fy = x - x0, y - y0
    total, weight_sum = 0.0, 0.0
    for dy, wy in ((0, 1 - fy), (1, fy)):
        for dx, wx in ((0, 1 - fx), (1, fx)):
            sx = min(max(x0 + dx, 0), src_w - 1)
            sy = min(max(y0 + dy, 0), src_h - 1)
            v = grid[sy][sx]
            if not is_nodata(v, nodata):
                total += v * wx * wy
                weight_sum += wx * wy
    return total / weight_sum if weight_sum > 0 else out_nd
