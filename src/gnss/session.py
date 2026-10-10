"""Static-session statistics and fix-quality assessment.

Scaling: :class:`Session` accumulates with Welford's online algorithm --
mean, variance, RMS and 2DRMS over an arbitrarily long static occupation
in O(1) memory. Pair with :func:`gnss.nmea.iter_sentences` to reduce a
whole log file without ever holding it in memory.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .nmea import GgaFix


@dataclass(frozen=True)
class Fix:
    """A single usable position fix."""
    lat: float
    lon: float
    height: float = 0.0
    quality: int = 1          # GGA fix-quality flag
    hdop: Optional[float] = None

    @classmethod
    def from_gga(cls, gga: GgaFix) -> Optional["Fix"]:
        if gga.quality == 0 or gga.lat is None or gga.lon is None:
            return None
        return cls(lat=gga.lat, lon=gga.lon,
                   height=gga.altitude or 0.0,
                   quality=gga.quality, hdop=gga.hdop)


QUALITY_NAMES = {
    0: "no_fix",
    1: "autonomous",
    2: "dgps",
    4: "rtk_fixed",
    5: "rtk_float",
}


def assess_quality(quality: int, hdop: Optional[float] = None) -> str:
    """Human label for a GGA fix-quality flag, downgraded by bad DOP."""
    name = QUALITY_NAMES.get(quality, f"unknown({quality})")
    if quality in (4, 5) and hdop is not None and hdop > 4:
        return name + "_high_dop"
    return name


@dataclass
class Session:
    """Incremental statistics over a static GNSS occupation (Welford)."""
    count: int = 0
    _mean_lat: float = 0.0
    _mean_lon: float = 0.0
    _mean_h: float = 0.0
    _m2_lat: float = 0.0
    _m2_lon: float = 0.0
    _m2_h: float = 0.0

    def add(self, fix: Fix) -> None:
        self.count += 1
        n = self.count
        for attr, m, m2 in (("lat", "_mean_lat", "_m2_lat"),
                            ("lon", "_mean_lon", "_m2_lon"),
                            ("height", "_mean_h", "_m2_h")):
            x = getattr(fix, attr)
            mean = getattr(self, m)
            delta = x - mean
            mean += delta / n
            setattr(self, m, mean)
            setattr(self, m2, getattr(self, m2) + delta * (x - mean))

    def mean_position(self) -> tuple[float, float, float]:
        """(lat, lon, height) of the session mean."""
        if not self.count:
            raise ValueError("Empty session")
        return (self._mean_lat, self._mean_lon, self._mean_h)

    def _std(self, m2: float) -> float:
        if self.count < 2:
            return 0.0
        return math.sqrt(m2 / (self.count - 1))

    def std(self) -> tuple[float, float, float]:
        """Sample std dev of (lat, lon, height); degrees, degrees, metres."""
        if not self.count:
            raise ValueError("Empty session")
        return (self._std(self._m2_lat), self._std(self._m2_lon),
                self._std(self._m2_h))

    def drms(self) -> float:
        """Distance RMS of horizontal scatter, in degrees."""
        s_lat, s_lon, _ = self.std()
        return math.sqrt(s_lat ** 2 + s_lon ** 2)

    def accuracy_2drms(self) -> float:
        """2*DRMS -- ~95% horizontal accuracy radius, in degrees."""
        return 2.0 * self.drms()

    def horizontal_accuracy_metres(self, at_lat: Optional[float] = None
                                   ) -> float:
        """2DRMS converted to metres at the session mean latitude."""
        lat = self._mean_lat if at_lat is None else at_lat
        m_per_deg = 111320.0 * math.cos(math.radians(lat))
        return self.accuracy_2drms() * m_per_deg
