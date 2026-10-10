"""Canonical job model for survey-field.

A field job is a :class:`Project` containing one or more :class:`BaseStation`
records and one or more :class:`RoverSession` objects, each holding the
:class:`SurveyPoint` shots taken against that base.

The model serialises to the canonical JSON interchange format
(``survey-field/job`` schema, see :mod:`field.jobfile`) so downstream engines
— the adjustment workflow (build #2), COGO drafting, the desktop app — all
read the same shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field, asdict
from typing import Any, Dict, Iterator, List, Optional

SCHEMA_VERSION = 1
JOB_FORMAT = "survey-field/job"


class Solution:
    """RTK solution-status values as written by Emlid Flow / ReachView 3."""
    FIX = "FIX"
    FLOAT = "FLOAT"
    SINGLE = "SINGLE"
    UNKNOWN = "UNKNOWN"


@dataclass
class SurveyPoint:
    """One collected rover point.

    Coordinates are stored exactly as exported: projected easting/northing/
    elevation in the project's coordinate system (when the export used one)
    plus geographic longitude/latitude/ellipsoidal height (always present for
    GNSS-collected points). Linear values are metres unless the export said
    otherwise (converted on import).
    """

    name: str
    code: str = ""
    description: str = ""
    # Projected coordinates (project CRS); None when export used geographic CS.
    easting: Optional[float] = None
    northing: Optional[float] = None
    elevation: Optional[float] = None
    # Geographic coordinates (WGS84-family as logged by the receiver).
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    ellipsoidal_height: Optional[float] = None
    # Quality / collection metadata.
    origin: str = ""               # e.g. "Global" for GNSS-collected points
    tilt_angle_deg: Optional[float] = None
    rms_e: Optional[float] = None
    rms_n: Optional[float] = None
    rms_u: Optional[float] = None
    rms_lateral: Optional[float] = None
    antenna_height_m: Optional[float] = None
    solution: str = Solution.UNKNOWN
    correction_type: str = ""      # e.g. "RTK", "NTRIP" (newer exports)
    averaging_start: Optional[str] = None   # ISO-8601 strings
    averaging_end: Optional[str] = None
    samples: Optional[int] = None
    pdop: Optional[float] = None
    baseline_m: Optional[float] = None
    # Unrecognised extra columns from the export, kept for provenance.
    meta: Dict[str, Any] = dc_field(default_factory=dict)

    def has_projected(self) -> bool:
        return self.easting is not None and self.northing is not None

    def has_geographic(self) -> bool:
        return self.longitude is not None and self.latitude is not None

    def has_any_position(self) -> bool:
        return self.has_projected() or self.has_geographic()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SurveyPoint":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BaseStation:
    """One distinct base position used during the job.

    Emlid logs the base's antenna *phase centre* (APC) per RTK point; the pole
    height and ARP→APC offset are already baked into those coordinates by the
    receiver, so no further height correction is applied on import.
    """

    id: str
    easting: Optional[float] = None
    northing: Optional[float] = None
    elevation: Optional[float] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    ellipsoidal_height: Optional[float] = None
    antenna_height_m: Optional[float] = None  # base pole height, when known
    source: str = "csv"          # "csv" | "manual" | "ntrip"
    n_points: int = 0            # rover points observed against this base

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BaseStation":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RoverSession:
    """One rover session: all points shot against a single base on one day."""

    id: str
    base_station_id: Optional[str]
    date: str = ""               # YYYY-MM-DD of first point's averaging start
    points: List[SurveyPoint] = dc_field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RoverSession":
        pts = [SurveyPoint.from_dict(p) for p in d.get("points", [])]
        return cls(id=d["id"], base_station_id=d.get("base_station_id"),
                   date=d.get("date", ""), points=pts)


@dataclass
class Project:
    """Top-level job container."""

    name: str
    crs: str = ""                # CS name string from the export, e.g. "NAD83(2011) / ..."
    source_files: List[str] = dc_field(default_factory=list)
    base_stations: List[BaseStation] = dc_field(default_factory=list)
    sessions: List[RoverSession] = dc_field(default_factory=list)
    # CRS provenance from `field import --target-crs` (additive, schema v1):
    # {"source_crs": {...}, "target_crs": {...}, "transform": {...}, "notes": [...]}.
    # None when the import ran without --target-crs; v1 job files omit the key.
    crs_provenance: Optional[Dict[str, Any]] = None

    def iter_points(self) -> Iterator[SurveyPoint]:
        for session in self.sessions:
            yield from session.points

    def n_points(self) -> int:
        return sum(len(s.points) for s in self.sessions)

    def base_station(self, base_id: Optional[str]) -> Optional[BaseStation]:
        for b in self.base_stations:
            if b.id == base_id:
                return b
        return None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "name": self.name,
            "crs": self.crs,
            "source_files": list(self.source_files),
            "base_stations": [b.to_dict() for b in self.base_stations],
            "sessions": [s.to_dict() for s in self.sessions],
        }
        # Additive: omitted entirely when unset so no-flag imports write
        # byte-identical v0.1.0 job files.
        if self.crs_provenance is not None:
            d["crs_provenance"] = self.crs_provenance
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Project":
        return cls(
            name=d.get("name", ""),
            crs=d.get("crs", ""),
            source_files=list(d.get("source_files", [])),
            base_stations=[BaseStation.from_dict(b) for b in d.get("base_stations", [])],
            sessions=[RoverSession.from_dict(s) for s in d.get("sessions", [])],
            crs_provenance=d.get("crs_provenance"),
        )
