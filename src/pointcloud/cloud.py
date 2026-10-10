"""PointCloud container, thinning, cropping, and chunked iteration.

Scaling: every operation here is single-pass O(n). ``iter_chunks`` lets
callers stream arbitrarily large clouds through bounded memory, and
``voxel_thin`` decimates dense clouds before expensive steps.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterator, Sequence

from .point import GROUND, UNCLASSIFIED, Point, as_point, xyz


@dataclass(frozen=True)
class CloudStats:
    """Summary statistics for a point cloud."""

    count: int
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float
    mean_z: float
    classes: dict[int, int]  # classification code -> count


def iter_chunks(points: Sequence, n: int) -> Iterator[list]:
    """Yield successive n-sized chunks covering the point sequence."""
    if n <= 0:
        raise ValueError("Chunk size must be positive")
    for i in range(0, len(points), n):
        yield list(points[i:i + n])


def voxel_thin(points: Sequence, voxel_size: float,
               keep: str = "lowest") -> list[Point]:
    """Decimate to at most one point per voxel (O(n), single pass).

    Args:
        voxel_size: Edge length of cubic voxels (same unit as coordinates).
        keep: ``"lowest"`` keeps the lowest-z point per voxel (good before
            ground classification); ``"first"`` keeps the first point seen.

    Returns a new list of canonical :class:`Point`.
    """
    if voxel_size <= 0:
        raise ValueError("voxel_size must be positive")
    if keep not in ("lowest", "first"):
        raise ValueError("keep must be 'lowest' or 'first'")
    voxels: dict[tuple[int, int, int], Point] = {}
    for p in points:
        x, y, z = xyz(p)
        key = (math.floor(x / voxel_size), math.floor(y / voxel_size),
               math.floor(z / voxel_size))
        pt = as_point(p)
        if key not in voxels:
            voxels[key] = pt
        elif keep == "lowest" and pt.z < voxels[key].z:
            voxels[key] = pt
    return list(voxels.values())


@dataclass
class PointCloud:
    """An in-memory point cloud with a CRS identifier."""

    points: list[Point] = field(default_factory=list)
    crs: str = ""

    def __post_init__(self) -> None:
        self.points = [as_point(p) for p in self.points]

    def __len__(self) -> int:
        return len(self.points)

    def bounds(self) -> tuple[float, float, float, float, float, float]:
        """(min_x, min_y, min_z, max_x, max_y, max_z)."""
        if not self.points:
            raise ValueError("Empty point cloud has no bounds")
        xs = [p.x for p in self.points]
        ys = [p.y for p in self.points]
        zs = [p.z for p in self.points]
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    def describe(self) -> CloudStats:
        """Summary statistics over the cloud."""
        if not self.points:
            raise ValueError("Cannot describe an empty point cloud")
        min_x, min_y, min_z, max_x, max_y, max_z = self.bounds()
        classes: dict[int, int] = {}
        for p in self.points:
            classes[p.classification] = classes.get(p.classification, 0) + 1
        return CloudStats(
            count=len(self.points),
            min_x=min_x, min_y=min_y, min_z=min_z,
            max_x=max_x, max_y=max_y, max_z=max_z,
            mean_z=sum(p.z for p in self.points) / len(self.points),
            classes=classes,
        )

    def crop(self, min_x: float, min_y: float,
             max_x: float, max_y: float) -> "PointCloud":
        """Return the points inside an axis-aligned bounding box."""
        pts = [p for p in self.points
               if min_x <= p.x <= max_x and min_y <= p.y <= max_y]
        return PointCloud(pts, crs=self.crs)

    def filter_classification(self, classes: Sequence[int]) -> "PointCloud":
        """Return points whose classification is in ``classes``."""
        wanted = set(classes)
        return PointCloud([p for p in self.points
                           if p.classification in wanted], crs=self.crs)

    def thin(self, voxel_size: float, keep: str = "lowest") -> "PointCloud":
        """Voxel-decimated copy of the cloud."""
        return PointCloud(voxel_thin(self.points, voxel_size, keep),
                          crs=self.crs)

    def chunks(self, n: int) -> Iterator[list[Point]]:
        """Iterate over the cloud in n-sized chunks (bounded memory)."""
        return iter_chunks(self.points, n)
