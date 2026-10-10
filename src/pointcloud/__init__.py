"""survey-pointcloud: point-cloud processing engine for surveying.

Pure-Python, dependency-free engine: LiDAR-style point model with ASPRS
classification codes, voxel thinning, ground classification, DEM gridding
(min/max/IDW), and grid-based cut/fill volumes. No UI, no file I/O --
points are duck-typed, so tuples, numpy rows, and laspy records work
directly, and DEM outputs drop straight into survey-raster.
"""

__version__ = "0.1.0"

from .classify import classify_ground_grid
from .cloud import CloudStats, PointCloud, iter_chunks, voxel_thin
from .dem import grid_maximum, grid_minimum, interpolate_idw
from .point import (
    BRIDGE_DECK,
    BUILDING,
    CREATED,
    GROUND,
    HIGH_VEGETATION,
    LOW_VEGETATION,
    MEDIUM_VEGETATION,
    NOISE,
    UNCLASSIFIED,
    WATER,
    CLASSIFICATION_NAMES,
    Point,
    as_point,
    xyz,
)
from .volumes import volume_between, volume_grid

__all__ = [
    "__version__",
    "Point",
    "as_point",
    "xyz",
    "CloudStats",
    "PointCloud",
    "iter_chunks",
    "voxel_thin",
    "classify_ground_grid",
    "grid_minimum",
    "grid_maximum",
    "interpolate_idw",
    "volume_grid",
    "volume_between",
    "CREATED",
    "UNCLASSIFIED",
    "GROUND",
    "LOW_VEGETATION",
    "MEDIUM_VEGETATION",
    "HIGH_VEGETATION",
    "BUILDING",
    "NOISE",
    "WATER",
    "BRIDGE_DECK",
    "CLASSIFICATION_NAMES",
]
