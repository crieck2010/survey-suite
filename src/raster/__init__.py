"""survey-raster: raster remote-sensing engine for surveying.

Pure-Python, dependency-free engine: an in-memory georeferenced raster
model, spectral indices, descriptive statistics, histograms, contrast
stretches, and resampling -- plus tiled window iteration so large scenes
can be processed in bounded memory. No UI, no file I/O: grids are plain
2D sequences, so numpy arrays work directly with zero coupling.
"""

__version__ = "0.1.0"

from .indices import evi, index_raster, ndvi, ndwi, normalized_difference, savi
from .raster import (
    DEFAULT_TRANSFORM,
    Grid,
    Raster,
    grid_shape,
    is_nodata,
    iter_windows,
    same_nodata,
)
from .resample import resample
from .stats import (
    RasterStats,
    describe,
    histogram,
    linear_stretch,
    percentile,
)

__all__ = [
    "__version__",
    "Grid",
    "Raster",
    "DEFAULT_TRANSFORM",
    "grid_shape",
    "is_nodata",
    "same_nodata",
    "iter_windows",
    "normalized_difference",
    "ndvi",
    "ndwi",
    "evi",
    "savi",
    "index_raster",
    "RasterStats",
    "describe",
    "histogram",
    "percentile",
    "linear_stretch",
    "resample",
]
