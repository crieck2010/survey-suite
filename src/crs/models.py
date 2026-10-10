"""Public data models for survey-crs. Standard library only."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .units import UNIT_DEGREE


@dataclass(frozen=True)
class CrsEntry:
    """One coordinate reference system in the registry.

    Every field is researched from the EPSG registry (see ``source_url``);
    projection parameters are stored normalized to degrees and metres in
    ``params``, with the official EPSG values/units preserved in
    ``params_epsg``.
    """
    name: str                 # official EPSG name, e.g. "NAD83(2011) / New York Long Island"
    epsg: int                 # EPSG code, e.g. 6538
    datum: str                # "NAD83(2011)" | "NAD83(CORS96)" | "WGS 84 (G2296)"
    kind: str                 # "tm" | "lcc" | "hotine" | "utm" | "geographic"
    params: Dict[str, Any]    # normalized projection parameters (deg, m)
    params_epsg: Dict[str, Dict[str, Any]]  # official EPSG parameter values + units
    unit: str                 # "m" | "ftUS" | "ft" | "deg"
    area_name: str            # EPSG area of use
    bbox: List[float]         # [lon_min, lat_min, lon_max, lat_max] of area of use
    state: Optional[str]      # US state name for SPCS entries, else None
    zone: Optional[str]       # zone label, e.g. "Long Island", "18N"
    source_url: str           # per-entry EPSG citation, e.g. https://epsg.io/6538
    notes: str                # curator notes ("" when none)
    group: str                # "spcs" | "utm" | "geographic"

    @property
    def is_projected(self) -> bool:
        return self.kind != "geographic"

    @property
    def unit_label(self) -> str:
        return {
            "m": "metre", "ftUS": "US survey foot",
            "ft": "international foot", "deg": "degree",
        }[self.unit]

    def describe(self) -> str:
        lines = [
            "%s  (EPSG:%d)" % (self.name, self.epsg),
            "  datum: %s" % self.datum,
            "  kind: %s   unit: %s" % (self.kind, self.unit_label),
            "  area: %s" % self.area_name,
        ]
        if self.params:
            lines.append("  parameters:")
            for k, v in self.params.items():
                lines.append("    %s = %r" % (k, v))
        lines.append("  source: %s" % self.source_url)
        if self.notes:
            lines.append("  notes: %s" % self.notes)
        return "\n".join(lines)


@dataclass(frozen=True)
class GeographicPoint:
    """A geographic position. Heights are ellipsoidal (v1 has no geoid)."""
    lat: float      # degrees, +N
    lon: float      # degrees, +E
    h: float = 0.0  # ellipsoidal height, metres
    datum: str = "NAD83(2011)"


@dataclass(frozen=True)
class ProjectedPoint:
    """A projected position in the CRS's own linear unit."""
    easting: float
    northing: float
    h: float = 0.0  # ellipsoidal height, metres
    epsg: int = 0
    unit: str = "m"


@dataclass(frozen=True)
class DatumPath:
    """How a datum shift is performed, with accuracy metadata.

    v1 performs only null (identity) approximations between distinct
    datums; each carries an estimated accuracy so callers never mistake
    the result for a survey-grade transformation.
    """
    from_datum: str
    to_datum: str
    method: str                  # "identity" | "null-approximation"
    accuracy_horizontal_m: float  # estimated 1-sigma horizontal accuracy
    region: str
    source: str
    warning: str

    @property
    def is_exact(self) -> bool:
        return self.method == "identity"


@dataclass(frozen=True)
class TransformResult:
    """Result of project/unproject/transform, with full provenance."""
    x: float            # easting (projected) or longitude (geographic), in `unit`
    y: float            # northing (projected) or latitude (geographic), in `unit`
    h: float            # ellipsoidal height, metres
    unit: str           # "m" | "ftUS" | "ft" | "deg"
    from_epsg: int
    to_epsg: int
    from_datum: str
    to_datum: str
    datum_path: DatumPath
    backend: str        # "survey-geodesy" | "internal"
    warnings: List[str] = field(default_factory=list)

    @property
    def is_geographic(self) -> bool:
        return self.unit == UNIT_DEGREE
