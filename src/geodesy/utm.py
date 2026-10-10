"""UTM convenience wrappers around the Transverse Mercator projection.

Zone number from longitude, WGS84 ellipsoid, k0 = 0.9996,
false easting 500000 m, false northing 0 / 10000000 m.
"""
from __future__ import annotations

from .ellipsoids import WGS84
from .transverse_mercator import tm_forward, tm_inverse

_K0 = 0.9996
_FALSE_EASTING = 500000.0


def utm_zone(lon_deg: float) -> int:
    """UTM zone number (1-60) for a longitude."""
    return int((lon_deg + 180.0) // 6) + 1


def _utm_params(lat_deg: float, lon_deg: float, zone: int | None):
    zone = utm_zone(lon_deg) if zone is None else zone
    if not 1 <= zone <= 60:
        raise ValueError("UTM zone must be 1-60")
    lon0 = zone * 6 - 183.0
    fn = 0.0 if lat_deg >= 0 else 10_000_000.0
    return zone, lon0, fn


def latlon_to_utm(lat_deg: float, lon_deg: float,
                  zone: int | None = None) -> tuple[float, float, int, str]:
    """Convert (lat, lon) to (easting, northing, zone, hemisphere)."""
    zone, lon0, fn = _utm_params(lat_deg, lon_deg, zone)
    e, n = tm_forward(lat_deg, lon_deg, lon0, k0=_K0,
                      false_easting=_FALSE_EASTING, false_northing=fn,
                      ellipsoid=WGS84)
    return e, n, zone, ("N" if lat_deg >= 0 else "S")


def utm_to_latlon(easting: float, northing: float, zone: int,
                  hemisphere: str = "N") -> tuple[float, float]:
    """Convert (easting, northing, zone) to (lat_deg, lon_deg)."""
    if hemisphere not in ("N", "S"):
        raise ValueError("hemisphere must be 'N' or 'S'")
    lon0 = zone * 6 - 183.0
    fn = 0.0 if hemisphere == "N" else 10_000_000.0
    return tm_inverse(easting, northing, lon0, k0=_K0,
                      false_easting=_FALSE_EASTING, false_northing=fn,
                      ellipsoid=WGS84)
