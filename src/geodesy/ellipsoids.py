"""Reference ellipsoids for geodetic computations."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ellipsoid:
    """A reference ellipsoid defined by semi-major axis and flattening."""

    name: str
    a: float  # semi-major axis, metres
    f: float  # flattening (1/f is the inverse flattening)

    @property
    def b(self) -> float:
        """Semi-minor axis, metres."""
        return self.a * (1.0 - self.f)

    @property
    def e2(self) -> float:
        """First eccentricity squared."""
        return 2.0 * self.f - self.f ** 2

    @property
    def ep2(self) -> float:
        """Second eccentricity squared."""
        return self.e2 / (1.0 - self.e2)

    @property
    def inv_f(self) -> float:
        return 1.0 / self.f


WGS84 = Ellipsoid("WGS84", a=6378137.0, f=1 / 298.257223563)
GRS80 = Ellipsoid("GRS80", a=6378137.0, f=1 / 298.257222101)
CLARKE1866 = Ellipsoid("Clarke 1866", a=6378206.4, f=1 / 294.9786982)
AIRY1830 = Ellipsoid("Airy 1830", a=6377563.396, f=1 / 299.3249646)

ELLIPSOIDS: dict[str, Ellipsoid] = {
    "WGS84": WGS84,
    "GRS80": GRS80,
    "Clarke1866": CLARKE1866,
    "Airy1830": AIRY1830,
}
