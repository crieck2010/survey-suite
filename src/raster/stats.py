"""Descriptive statistics, histograms, and contrast stretches.

All functions skip nodata cells and accept any 2D row-major grid.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .raster import Grid, is_nodata


@dataclass(frozen=True)
class RasterStats:
    """Descriptive statistics over the valid cells of a grid."""

    minimum: float
    maximum: float
    mean: float
    std: float  # population standard deviation
    count: int  # valid cells
    nodata_count: int


def _valid_values(grid: Grid, nodata: float | None) -> list[float]:
    vals = [v for row in grid for v in row if not is_nodata(v, nodata)]
    if not vals:
        raise ValueError("Grid has no valid cells")
    return vals


def describe(grid: Grid, nodata: float | None = None) -> RasterStats:
    """Min, max, mean, and population std dev over valid cells."""
    nodata_count = sum(1 for row in grid for v in row if is_nodata(v, nodata))
    vals = _valid_values(grid, nodata)
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return RasterStats(minimum=min(vals), maximum=max(vals), mean=mean,
                       std=math.sqrt(var), count=len(vals),
                       nodata_count=nodata_count)


def histogram(grid: Grid, bins: int = 256,
              value_range: tuple[float, float] | None = None,
              nodata: float | None = None) -> list[int]:
    """Equal-width histogram counts over valid cells.

    ``value_range`` defaults to the data min/max; values outside the range
    are clipped into the first/last bin.
    """
    if bins <= 0:
        raise ValueError("bins must be positive")
    vals = _valid_values(grid, nodata)
    lo, hi = value_range if value_range else (min(vals), max(vals))
    if hi <= lo:
        counts = [0] * bins
        counts[0] = len(vals)
        return counts
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        idx = int((v - lo) / width)
        counts[min(max(idx, 0), bins - 1)] += 1
    return counts


def percentile(grid: Grid, q: float,
               nodata: float | None = None) -> float:
    """The q-th percentile (0-100) of valid cells, linear interpolation."""
    if not 0 <= q <= 100:
        raise ValueError("q must be in [0, 100]")
    vals = sorted(_valid_values(grid, nodata))
    if len(vals) == 1:
        return vals[0]
    rank = q / 100 * (len(vals) - 1)
    lo, hi = math.floor(rank), math.ceil(rank)
    if lo == hi:
        return vals[lo]
    frac = rank - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def linear_stretch(grid: Grid, p_low: float = 2.0, p_high: float = 98.0,
                   out_min: float = 0.0, out_max: float = 255.0,
                   nodata: float | None = None) -> list[list[float]]:
    """Percentile-based contrast stretch for display.

    Valid cells are mapped from [p_low, p_high] percentiles to
    [out_min, out_max] and clipped; nodata cells stay nodata.
    """
    lo = percentile(grid, p_low, nodata)
    hi = percentile(grid, p_high, nodata)
    out_nd = float("nan") if nodata is None else nodata
    span = hi - lo
    out: list[list[float]] = []
    for row in grid:
        row_out = []
        for v in row:
            if is_nodata(v, nodata):
                row_out.append(out_nd)
            elif span == 0:
                row_out.append((out_min + out_max) / 2)
            else:
                scaled = out_min + (v - lo) / span * (out_max - out_min)
                row_out.append(min(max(scaled, out_min), out_max))
        out.append(row_out)
    return out
