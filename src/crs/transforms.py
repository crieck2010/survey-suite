"""Coordinate transformation pipelines: project / unproject / transform.

Heights are ellipsoidal and carried through unchanged (v1 has no geoid /
NAVD88 support -- see docs/DATUMS.md).
"""
from __future__ import annotations

from typing import Tuple

from . import projections, registry
from .datums import datum_path
from .models import CrsEntry, TransformResult
from .units import from_metres, to_metres


def _project_metres(lat: float, lon: float, entry: CrsEntry) -> Tuple[float, float]:
    """Project to (E, N) in metres for a projected entry."""
    p = entry.params
    ell = projections.ellipsoid_for_datum(entry.datum)
    if entry.kind == "tm":
        return projections.tm_forward(lat, lon, p["lon0"], p["k0"], p["fe"],
                                      p["fn"], p["lat0"], ell)
    if entry.kind == "utm":
        return projections.tm_forward(lat, lon, p["lon0"], p["k0"], p["fe"],
                                      p["fn"], 0.0, ell)
    if entry.kind == "lcc":
        return projections.lcc_forward(lat, lon, p["lat0"], p["lon0"],
                                       p["lat1"], p["lat2"], p["fe"], p["fn"],
                                       ell)
    if entry.kind == "hotine":
        return projections.hotine_forward(lat, lon, p["latc"], p["lonc"],
                                          p["azimuth"], p["rectified_skew_angle"],
                                          p["kc"], p["fe"], p["fn"], ell)
    raise ValueError("cannot project kind %r" % (entry.kind,))


def _unproject_metres(E: float, N: float, entry: CrsEntry) -> Tuple[float, float]:
    """Unproject (E, N) in metres to (lat, lon) for a projected entry."""
    p = entry.params
    ell = projections.ellipsoid_for_datum(entry.datum)
    if entry.kind == "tm":
        return projections.tm_inverse(E, N, p["lon0"], p["k0"], p["fe"],
                                      p["fn"], p["lat0"], ell)
    if entry.kind == "utm":
        return projections.tm_inverse(E, N, p["lon0"], p["k0"], p["fe"],
                                      p["fn"], 0.0, ell)
    if entry.kind == "lcc":
        return projections.lcc_inverse(E, N, p["lat0"], p["lon0"],
                                       p["lat1"], p["lat2"], p["fe"], p["fn"],
                                       ell)
    if entry.kind == "hotine":
        return projections.hotine_inverse(E, N, p["latc"], p["lonc"],
                                          p["azimuth"], p["rectified_skew_angle"],
                                          p["kc"], p["fe"], p["fn"], ell)
    raise ValueError("cannot unproject kind %r" % (entry.kind,))


def _area_warning(entry: CrsEntry, lon: float, lat: float):
    w, s, e_, n = entry.bbox
    if not (w <= lon <= e_ and s <= lat <= n):
        return ("point (%.6f, %.6f) is outside the area of use of %s"
                % (lon, lat, entry.name))
    return None


def _to_geo(x: float, y: float, entry: CrsEntry):
    """(x, y) in the entry's own coordinates -> (lat, lon, h-in)."""
    if not entry.is_projected:
        return y, x  # x=lon, y=lat for geographic entries
    E = to_metres(x, entry.unit)
    N = to_metres(y, entry.unit)
    return _unproject_metres(E, N, entry)


def _from_geo(lat: float, lon: float, entry: CrsEntry):
    """(lat, lon) -> (x, y) in the entry's own coordinates."""
    if not entry.is_projected:
        return lon, lat
    E, N = _project_metres(lat, lon, entry)
    return from_metres(E, entry.unit), from_metres(N, entry.unit)


def project(lat: float, lon: float, epsg: int, h: float = 0.0) -> TransformResult:
    """Project geographic coordinates (in the entry's datum) to the CRS.

    For a geographic entry this is the identity.
    """
    entry = registry.by_epsg(epsg)
    x, y = _from_geo(lat, lon, entry)
    path = datum_path(entry.datum, entry.datum)
    warnings = []
    w = _area_warning(entry, lon, lat)
    if w:
        warnings.append(w)
    return TransformResult(
        x=x, y=y, h=h, unit=entry.unit,
        from_epsg=epsg, to_epsg=epsg,
        from_datum=entry.datum, to_datum=entry.datum,
        datum_path=path, backend=projections.backend_name(),
        warnings=warnings,
    )


def unproject(x: float, y: float, epsg: int, h: float = 0.0) -> TransformResult:
    """Unproject (easting, northing) -- or (lon, lat) for geographic entries.

    Result x/y are always (lon, lat) in degrees for the inverse direction.
    """
    entry = registry.by_epsg(epsg)
    lat, lon = _to_geo(x, y, entry)
    path = datum_path(entry.datum, entry.datum)
    return TransformResult(
        x=lon, y=lat, h=h, unit="deg",
        from_epsg=epsg, to_epsg=epsg,
        from_datum=entry.datum, to_datum=entry.datum,
        datum_path=path, backend=projections.backend_name(),
        warnings=[],
    )


def transform_coords(x: float, y: float, from_epsg: int, to_epsg: int,
                     h: float = 0.0) -> TransformResult:
    """Convert coordinates from one registry CRS to another.

    For a geographic source CRS, x=longitude and y=latitude in degrees;
    for a projected source CRS, x=easting and y=northing in the CRS unit.
    The result carries the target CRS unit, plus datum-path provenance.
    Heights are ellipsoidal and pass through unchanged (no geoid in v1).
    """
    src = registry.by_epsg(from_epsg)
    dst = registry.by_epsg(to_epsg)
    lat, lon = _to_geo(x, y, src)
    path = datum_path(src.datum, dst.datum)
    warnings = []
    if not path.is_exact:
        warnings.append("datum: %s" % path.warning)
    w = _area_warning(dst, lon, lat)
    if w:
        warnings.append(w)
    rx, ry = _from_geo(lat, lon, dst)
    return TransformResult(
        x=rx, y=ry, h=h, unit=dst.unit,
        from_epsg=from_epsg, to_epsg=to_epsg,
        from_datum=src.datum, to_datum=dst.datum,
        datum_path=path, backend=projections.backend_name(),
        warnings=warnings,
    )
