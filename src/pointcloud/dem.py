"""DEM gridding: minimum/maximum surfaces and IDW interpolation.

Interoperability: outputs are plain row-major grids that drop directly
into ``survey-raster`` -- e.g. ``Raster(grid_minimum(...), transform=...,
crs=...)`` -- for indices, hillshading, and further analysis. The DTM
(minimum) / DSM (maximum) distinction follows standard LiDAR practice.

Scaling: min/max gridding is single-pass O(n). IDW is O(cells x points)
brute force in 0.1.0 -- thin the cloud first (voxel_thin) or tile the
area for large jobs; a spatial index is on the roadmap.
"""
from __future__ import annotations

import math
from typing import Sequence

from .point import xyz

Grid = list[list[float]]


def _cell_index(x: float, y: float, origin_x: float, origin_y: float,
                pixel_size: float, width: int, height: int):
    col = int(math.floor((x - origin_x) / pixel_size))
    row = int(math.floor((y - origin_y) / pixel_size))
    if 0 <= row < height and 0 <= col < width:
        return row, col
    return None


def grid_minimum(points: Sequence, origin_x: float, origin_y: float,
                 pixel_size: float, width: int, height: int,
                 nodata: float = float("nan")) -> Grid:
    """Lowest z per cell -- DTM-style surface. Empty cells are nodata."""
    return _grid_extreme(points, origin_x, origin_y, pixel_size, width,
                         height, nodata, take_min=True)


def grid_maximum(points: Sequence, origin_x: float, origin_y: float,
                 pixel_size: float, width: int, height: int,
                 nodata: float = float("nan")) -> Grid:
    """Highest z per cell -- DSM-style surface. Empty cells are nodata."""
    return _grid_extreme(points, origin_x, origin_y, pixel_size, width,
                         height, nodata, take_min=False)


def _grid_extreme(points, origin_x, origin_y, pixel_size, width, height,
                  nodata, take_min: bool) -> Grid:
    if pixel_size <= 0 or width <= 0 or height <= 0:
        raise ValueError("Grid parameters must be positive")
    grid: Grid = [[nodata] * width for _ in range(height)]
    for p in points:
        x, y, z = xyz(p)
        idx = _cell_index(x, y, origin_x, origin_y, pixel_size, width, height)
        if idx is None:
            continue
        row, col = idx
        cur = grid[row][col]
        if isinstance(cur, float) and math.isnan(cur):
            grid[row][col] = z
        elif (z < cur) if take_min else (z > cur):
            grid[row][col] = z
    return grid


def interpolate_idw(points: Sequence, origin_x: float, origin_y: float,
                    pixel_size: float, width: int, height: int,
                    power: float = 2.0, radius: float | None = None,
                    nodata: float = float("nan")) -> Grid:
    """Inverse-distance-weighted interpolation to a regular grid.

    Cell centres with a point closer than ~1e-9 take that point's z
    directly. With ``radius=None`` every point influences every cell;
    otherwise only points within ``radius`` contribute, and cells with
    no neighbours are nodata.
    """
    if pixel_size <= 0 or width <= 0 or height <= 0:
        raise ValueError("Grid parameters must be positive")
    if power <= 0:
        raise ValueError("power must be positive")
    pts = [(xyz(p)[0], xyz(p)[1], xyz(p)[2]) for p in points]
    grid: Grid = [[nodata] * width for _ in range(height)]
    for row in range(height):
        cy = origin_y + (row + 0.5) * pixel_size
        for col in range(width):
            cx = origin_x + (col + 0.5) * pixel_size
            total, wsum = 0.0, 0.0
            for px, py, pz in pts:
                d = math.hypot(px - cx, py - cy)
                if d < 1e-9:
                    total, wsum = pz, 1.0
                    break
                if radius is not None and d > radius:
                    continue
                w = 1.0 / d ** power
                total += pz * w
                wsum += w
            if wsum > 0:
                grid[row][col] = total / wsum
    return grid
