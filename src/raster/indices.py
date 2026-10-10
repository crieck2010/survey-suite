"""Spectral indices for multispectral imagery.

All functions accept any 2D row-major grids (nested lists or numpy arrays)
and return plain nested lists. Pixels where either input is nodata, or
where the index is undefined (zero denominator), are set to nodata in the
output -- NaN when no nodata value is given.
"""
from __future__ import annotations

import math
from typing import Sequence

from .raster import Grid, Raster, grid_shape, is_nodata, same_nodata

__all__ = ["normalized_difference", "ndvi", "ndwi", "evi", "savi",
           "index_raster"]


def _check_match(a: Grid, b: Grid) -> tuple[int, int]:
    ha, wa = grid_shape(a)
    hb, wb = grid_shape(b)
    if (ha, wa) != (hb, wb):
        raise ValueError(f"Grid shapes differ: {(ha, wa)} vs {(hb, wb)}")
    return ha, wa


def _out_nodata(nodata: float | None) -> float:
    return float("nan") if nodata is None else nodata


def normalized_difference(a: Grid, b: Grid,
                          nodata: float | None = None) -> list[list[float]]:
    """(a - b) / (a + b), e.g. the generic form behind NDVI/NDWI."""
    h, w = _check_match(a, b)
    out_nd = _out_nodata(nodata)
    out: list[list[float]] = []
    for i in range(h):
        row_out: list[float] = []
        for j in range(w):
            va, vb = a[i][j], b[i][j]
            denom = va + vb
            if is_nodata(va, nodata) or is_nodata(vb, nodata) or denom == 0:
                row_out.append(out_nd)
            else:
                row_out.append((va - vb) / denom)
        out.append(row_out)
    return out


def ndvi(nir: Grid, red: Grid,
         nodata: float | None = None) -> list[list[float]]:
    """Normalized Difference Vegetation Index: (NIR - Red) / (NIR + Red)."""
    return normalized_difference(nir, red, nodata)


def ndwi(green: Grid, nir: Grid,
         nodata: float | None = None) -> list[list[float]]:
    """Normalized Difference Water Index: (Green - NIR) / (Green + NIR)."""
    return normalized_difference(green, nir, nodata)


def evi(nir: Grid, red: Grid, blue: Grid,
        nodata: float | None = None) -> list[list[float]]:
    """Enhanced Vegetation Index: 2.5*(NIR-Red) / (NIR + 6*Red - 7.5*Blue + 1)."""
    h, w = _check_match(nir, red)
    _check_match(nir, blue)
    out_nd = _out_nodata(nodata)
    out: list[list[float]] = []
    for i in range(h):
        row_out = []
        for j in range(w):
            vn, vr, vb = nir[i][j], red[i][j], blue[i][j]
            denom = vn + 6 * vr - 7.5 * vb + 1
            if (is_nodata(vn, nodata) or is_nodata(vr, nodata)
                    or is_nodata(vb, nodata) or denom == 0):
                row_out.append(out_nd)
            else:
                row_out.append(2.5 * (vn - vr) / denom)
        out.append(row_out)
    return out


def savi(nir: Grid, red: Grid, L: float = 0.5,
         nodata: float | None = None) -> list[list[float]]:
    """Soil-Adjusted Vegetation Index: ((NIR-Red)/(NIR+Red+L)) * (1+L)."""
    h, w = _check_match(nir, red)
    out_nd = _out_nodata(nodata)
    out: list[list[float]] = []
    for i in range(h):
        row_out = []
        for j in range(w):
            vn, vr = nir[i][j], red[i][j]
            denom = vn + vr + L
            if is_nodata(vn, nodata) or is_nodata(vr, nodata) or denom == 0:
                row_out.append(out_nd)
            else:
                row_out.append((vn - vr) / denom * (1 + L))
        out.append(row_out)
    return out


def index_raster(nir: Raster, red: Raster,
                 func=ndvi) -> Raster:
    """Apply a two-band index to georeferenced bands, keeping georeferencing.

    Both rasters must share shape, transform, and nodata handling; the
    result inherits the transform/CRS of ``nir``. Works tile-by-tile for
    large scenes: ``Raster(nir.windows(...))``-style loops stay in this
    package's public API.
    """
    if nir.shape != red.shape:
        raise ValueError(f"Band shapes differ: {nir.shape} vs {red.shape}")
    if nir.transform != red.transform or nir.crs != red.crs:
        raise ValueError("Bands are not co-registered (transform/CRS differ)")
    # Unify the nodata marker; undefined index cells are always marked NaN
    # when the inputs carried no nodata value.
    nodata = nir.nodata if same_nodata(nir.nodata, red.nodata) else float("nan")
    data = func(nir.data, red.data, nodata)
    result_nodata = nodata if nodata is not None else float("nan")
    return Raster(data, transform=nir.transform, crs=nir.crs,
                  nodata=result_nodata)
