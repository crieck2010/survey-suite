"""In-memory raster model and georeferencing helpers.

Design notes for interoperability and scaling:

- Pixel functions throughout this package accept any 2D row-major sequence
  (``grid[row][col]``): nested lists, tuples, or -- without any dependency --
  numpy arrays, which natively support this protocol. Outputs are plain
  nested lists, the most portable representation; ``numpy.asarray`` converts
  back at zero copy cost.
- Georeferencing follows the GDAL geotransform convention so a ``Raster``
  maps 1:1 onto rasterio/GDAL datasets when an I/O layer is added later
  (roadmap: ``survey-suite`` adapters). The engine itself never touches
  the filesystem.
- Large rasters are handled by tiling: :func:`iter_windows` yields
  non-overlapping (or overlapping) windows and :meth:`Raster.window`
  extracts them with corrected geotransforms, so arbitrarily large scenes
  can be processed in bounded memory.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterator, Sequence

Grid = Sequence[Sequence[float]]

# (origin_x, pixel_width, row_rotation, origin_y, col_rotation, pixel_height)
# North-up imagery has a negative pixel_height.
DEFAULT_TRANSFORM = (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)


def is_nodata(value: float | None, nodata: float | None) -> bool:
    """Nodata test that is NaN-aware (NaN != NaN, so == is not enough)."""
    if value is None:
        return True
    if nodata is None:
        return False
    if isinstance(nodata, float) and math.isnan(nodata):
        return isinstance(value, float) and math.isnan(value)
    return value == nodata


def same_nodata(a: float | None, b: float | None) -> bool:
    """Nodata equality that treats NaN as equal to NaN."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and math.isnan(a):
        return isinstance(b, float) and math.isnan(b)
    return a == b


def grid_shape(grid: Grid) -> tuple[int, int]:
    """Return (height, width) of a 2D grid; raises on ragged input."""
    height = len(grid)
    if height == 0:
        raise ValueError("Grid has no rows")
    width = len(grid[0])
    if any(len(row) != width for row in grid):
        raise ValueError("Grid rows have inconsistent lengths")
    return height, width


def iter_windows(width: int, height: int, tile: int = 512,
                 overlap: int = 0) -> Iterator[tuple[int, int, int, int]]:
    """Yield (row_off, col_off, win_width, win_height) covering the raster.

    With ``overlap=0`` the windows tile the raster exactly once, so a
    per-pixel computation can run in bounded memory by processing one
    window at a time. A nonzero overlap is useful for focal (neighbourhood)
    operators, which need context around each tile.
    """
    if tile <= 0:
        raise ValueError("tile must be positive")
    if overlap < 0 or overlap * 2 >= tile:
        raise ValueError("overlap must satisfy 0 <= overlap < tile/2")
    step = tile - overlap
    row = 0
    while row < height:
        col = 0
        win_h = min(tile, height - row)
        while col < width:
            win_w = min(tile, width - col)
            yield row, col, win_w, win_h
            if col + tile >= width:
                break
            col += step
        if row + tile >= height:
            break
        row += step


@dataclass
class Raster:
    """An in-memory raster band with georeferencing.

    Attributes:
        data: 2D row-major pixel grid (``data[row][col]``).
        transform: GDAL-style geotransform
            ``(origin_x, pixel_width, 0, origin_y, 0, pixel_height)``.
            Pixel coordinates below refer to pixel *centres*.
        crs: Coordinate reference identifier, e.g. ``"EPSG:32618"``.
        nodata: Nodata marker (sentinel value, NaN, or None for "all valid").
    """

    data: Grid
    transform: tuple[float, float, float, float, float, float] = DEFAULT_TRANSFORM
    crs: str = ""
    nodata: float | None = None

    def __post_init__(self) -> None:
        grid_shape(self.data)
        if len(self.transform) != 6:
            raise ValueError("transform must be a 6-element GDAL geotransform")

    @property
    def height(self) -> int:
        return len(self.data)

    @property
    def width(self) -> int:
        return len(self.data[0])

    @property
    def shape(self) -> tuple[int, int]:
        return self.height, self.width

    def rowcol_to_xy(self, row: float, col: float) -> tuple[float, float]:
        """Map (fractional) pixel coordinates to projected x/y (pixel centre at integer+0.5)."""
        ox, pw, _, oy, _, ph = self.transform
        return ox + (col + 0.5) * pw, oy + (row + 0.5) * ph

    def xy_to_rowcol(self, x: float, y: float) -> tuple[int, int]:
        """Map projected x/y to integer (row, col). Raises if outside the raster."""
        ox, pw, _, oy, _, ph = self.transform
        if pw == 0 or ph == 0:
            raise ValueError("Degenerate geotransform")
        col = int(math.floor((x - ox) / pw - 0.5))
        row = int(math.floor((y - oy) / ph - 0.5))
        if not (0 <= row < self.height and 0 <= col < self.width):
            raise ValueError(f"Point ({x}, {y}) falls outside the raster")
        return row, col

    def window(self, row_off: int, col_off: int,
               win_width: int, win_height: int) -> "Raster":
        """Extract a window as a new Raster with a shifted geotransform."""
        if not (0 <= row_off < self.height and 0 <= col_off < self.width):
            raise ValueError("Window origin outside the raster")
        if row_off + win_height > self.height or col_off + win_width > self.width:
            raise ValueError("Window extends beyond the raster")
        ox, pw, rx, oy, cx, ph = self.transform
        sub = [list(row[col_off:col_off + win_width])
               for row in self.data[row_off:row_off + win_height]]
        new_transform = (ox + col_off * pw, pw, rx, oy + row_off * ph, cx, ph)
        return Raster(sub, transform=new_transform, crs=self.crs,
                      nodata=self.nodata)

    def windows(self, tile: int = 512, overlap: int = 0) -> Iterator["Raster"]:
        """Iterate over the raster tile by tile (see :func:`iter_windows`)."""
        for row, col, w, h in iter_windows(self.width, self.height, tile, overlap):
            yield self.window(row, col, w, h)
