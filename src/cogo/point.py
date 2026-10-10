"""Survey point model: northing/easting plane coordinates."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    """A plane-coordinate survey point.

    Attributes:
        northing: Y coordinate (north positive).
        easting: X coordinate (east positive).
        name: Optional point identifier / station name.
        elevation: Optional orthometric height. Defaults to 0.0.
    """

    northing: float
    easting: float
    name: str = ""
    elevation: float = 0.0

    def shifted(self, d_northing: float, d_easting: float, name: str = "") -> "Point":
        """Return a new point offset by the given deltas."""
        return Point(
            northing=self.northing + d_northing,
            easting=self.easting + d_easting,
            name=name or self.name,
            elevation=self.elevation,
        )
