"""Emlid Flow / ReachView 3 CSV import.

The export format has drifted across app versions (17-column ReachView 3,
29-column Emlid Flow, 31+-column Emlid Flow 360 with "Tilt angle" and
"Correction type"), so parsing is **header-driven**: columns are matched by
normalised header name, never by position. Unknown columns are kept on the
point's ``meta`` dict so nothing is silently dropped.

Column reference (researched 2026-09-26 from Emlid docs, changelogs and real
exports shared on the Emlid community forum):

* ReachView 3 classic: Name, Easting, Northing, Elevation, Description,
  Easting RMS, Northing RMS, Elevation RMS, Lateral RMS, Antenna height,
  Solution status, Averaging start, Averaging end, Samples, Base easting,
  Base northing, Base elevation, Baseline
* Emlid Flow adds: Code, Longitude, Latitude, Ellipsoidal height, Origin,
  Antenna height units, PDOP, Base longitude, Base latitude,
  Base ellipsoidal height, CS name
* Emlid Flow 360 adds: Tilt angle (after Origin), Correction type
  (after Solution status)

Solution status values: FIX, FLOAT, SINGLE. "Origin" is "Global" for
GNSS-collected points. Base easting/northing/elevation are the base's antenna
*phase centre* (pole height + ARP->APC offset already applied by the receiver).
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from typing import Dict, IO, List, Optional, Sequence, Tuple

from .models import BaseStation, Project, RoverSession, Solution, SurveyPoint

#: Emlid's imperial exports write antenna height in feet ("Antenna height units").
_FT_TO_M = 0.3048


def _norm(header: str) -> str:
    """Normalise a CSV header for matching: lower-case, single spaces."""
    return re.sub(r"\s+", " ", (header or "").strip().lower())


# Normalised header -> SurveyPoint attribute. Covers every known Emlid
# Flow / ReachView 3 export variant; absence of a column is fine.
_HEADER_MAP: Dict[str, str] = {
    "name": "name",
    "code": "code",
    "easting": "easting",
    "northing": "northing",
    "elevation": "elevation",
    "description": "description",
    "longitude": "longitude",
    "latitude": "latitude",
    "ellipsoidal height": "ellipsoidal_height",
    "ellipsoid height": "ellipsoidal_height",
    "origin": "origin",
    "tilt angle": "tilt_angle_deg",
    "easting rms": "rms_e",
    "northing rms": "rms_n",
    "elevation rms": "rms_u",
    "lateral rms": "rms_lateral",
    "antenna height": "antenna_height_m",
    "solution status": "solution",
    "correction type": "correction_type",
    "averaging start": "averaging_start",
    "averaging end": "averaging_end",
    "samples": "samples",
    "pdop": "pdop",
    "baseline": "baseline_m",
    # Base-station columns are handled separately (per-session base records).
    "base easting": "__base_easting",
    "base northing": "__base_northing",
    "base elevation": "__base_elevation",
    "base longitude": "__base_longitude",
    "base latitude": "__base_latitude",
    "base ellipsoidal height": "__base_ellipsoidal_height",
    "cs name": "__cs_name",
    "antenna height units": "__antenna_units",
}

#: Units-column values that mean the antenna height is in feet.
_FEET_MARKERS = {"ft", "feet", "foot", "usft", "ftus", "international feet"}


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    s = value.strip().replace(",", "")
    if not s or s.lower() in {"n/a", "na", "-", "--", "null", "none"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(value: Optional[str]) -> Optional[int]:
    f = _to_float(value)
    return None if f is None else int(f)


def _to_solution(value: Optional[str]) -> str:
    if not value:
        return Solution.UNKNOWN
    s = value.strip().upper()
    if s in (Solution.FIX, Solution.FLOAT, Solution.SINGLE):
        return s
    return Solution.UNKNOWN


def _to_timestamp(value: Optional[str]) -> Optional[str]:
    """Normalise Emlid's ``2024-03-26 12:49:09.4 UTC+00:00`` to ISO-8601."""
    if not value or not value.strip():
        return None
    s = value.strip()
    # Emlid writes "2024-03-26 12:49:09.4 UTC+00:00"; strip the UTC label and
    # attach the numeric offset so fromisoformat() parses it.
    s = s.replace("UTC", "").strip()
    s = re.sub(r"\s+([+-]\d{2}:?\d{2})$", r"\1", s)
    if "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Fall back to common variants.
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            return s  # keep the raw string rather than losing the data
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def detect_dialect(headers: Sequence[str]) -> str:
    """Classify an Emlid export by its header set.

    Returns one of ``"emlid-flow-360"``, ``"emlid-flow"``, ``"reachview3"``,
    ``"penzd-import"`` (the minimal import template), or ``"unknown"``.
    """
    norms = {_norm(h) for h in headers}
    if "tilt angle" in norms or "correction type" in norms:
        return "emlid-flow-360"
    if "cs name" in norms or "ellipsoidal height" in norms:
        return "emlid-flow"
    if "solution status" in norms and "base easting" in norms:
        return "reachview3"
    if {"name", "easting", "northing", "elevation"} <= norms:
        return "penzd-import"
    return "unknown"


def _is_feet(units: Optional[str]) -> bool:
    return bool(units) and units.strip().lower() in _FEET_MARKERS


class EmlidParseResult:
    """Parsed rows plus per-row base info and project CS name."""

    def __init__(self) -> None:
        self.points: List[SurveyPoint] = []
        # Parallel list: (base coords dict, cs name) per point.
        self.base_info: List[Tuple[Dict[str, Optional[float]], str]] = []
        self.dialect: str = "unknown"
        self.headers: List[str] = []


def parse_emlid_csv(file: IO[str]) -> EmlidParseResult:
    """Parse an Emlid Flow / ReachView 3 CSV export.

    Raises :class:`ValueError` when the header row is not a recognisable
    Emlid export.
    """
    # Tolerate a UTF-8 BOM, which Emlid Flow writes.
    first = file.read(1)
    if first != "\ufeff" and first:
        file.seek(0)
    reader = csv.DictReader(file)
    if reader.fieldnames is None:
        raise ValueError("empty CSV: no header row found")
    result = EmlidParseResult()
    result.headers = list(reader.fieldnames)
    result.dialect = detect_dialect(result.headers)
    if result.dialect == "unknown":
        raise ValueError(
            "unrecognised CSV header row; not an Emlid Flow / ReachView 3 export. "
            f"Headers seen: {result.headers}"
        )

    col_attr = {_norm(h): _HEADER_MAP.get(_norm(h)) for h in result.headers}

    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue  # skip blank lines
        # Normalise row keys once (csv keeps raw header text as keys).
        nrow = {_norm(k): (v or "") for k, v in row.items() if k}
        attrs: Dict[str, object] = {}
        meta: Dict[str, str] = {}
        units_raw: Optional[str] = None
        base: Dict[str, Optional[float]] = {}
        cs_name = ""
        for nkey, raw in nrow.items():
            attr = col_attr.get(nkey)
            if attr is None:
                if raw.strip():
                    meta[nkey] = raw.strip()
                continue
            if attr == "__antenna_units":
                units_raw = raw
            elif attr == "__cs_name":
                cs_name = raw.strip()
            elif attr.startswith("__base_"):
                base[attr[7:]] = _to_float(raw)
            elif attr == "solution":
                attrs[attr] = _to_solution(raw)
            elif attr in ("averaging_start", "averaging_end"):
                attrs[attr] = _to_timestamp(raw)
            elif attr == "samples":
                attrs[attr] = _to_int(raw)
            elif attr in ("name", "code", "description", "origin",
                          "correction_type"):
                attrs[attr] = raw.strip()
            else:
                attrs[attr] = _to_float(raw)

        if _is_feet(units_raw) and attrs.get("antenna_height_m") is not None:
            attrs["antenna_height_m"] = attrs["antenna_height_m"] * _FT_TO_M

        name = attrs.get("name") or ""
        point = SurveyPoint(
            name=str(name),
            code=str(attrs.get("code") or ""),
            description=str(attrs.get("description") or ""),
            easting=attrs.get("easting"),  # type: ignore[arg-type]
            northing=attrs.get("northing"),  # type: ignore[arg-type]
            elevation=attrs.get("elevation"),  # type: ignore[arg-type]
            longitude=attrs.get("longitude"),  # type: ignore[arg-type]
            latitude=attrs.get("latitude"),  # type: ignore[arg-type]
            ellipsoidal_height=attrs.get("ellipsoidal_height"),  # type: ignore[arg-type]
            origin=str(attrs.get("origin") or ""),
            tilt_angle_deg=attrs.get("tilt_angle_deg"),  # type: ignore[arg-type]
            rms_e=attrs.get("rms_e"),  # type: ignore[arg-type]
            rms_n=attrs.get("rms_n"),  # type: ignore[arg-type]
            rms_u=attrs.get("rms_u"),  # type: ignore[arg-type]
            rms_lateral=attrs.get("rms_lateral"),  # type: ignore[arg-type]
            antenna_height_m=attrs.get("antenna_height_m"),  # type: ignore[arg-type]
            solution=str(attrs.get("solution") or Solution.UNKNOWN),
            correction_type=str(attrs.get("correction_type") or ""),
            averaging_start=attrs.get("averaging_start"),  # type: ignore[arg-type]
            averaging_end=attrs.get("averaging_end"),  # type: ignore[arg-type]
            samples=attrs.get("samples"),  # type: ignore[arg-type]
            pdop=attrs.get("pdop"),  # type: ignore[arg-type]
            baseline_m=attrs.get("baseline_m"),  # type: ignore[arg-type]
            meta=meta,
        )
        result.points.append(point)
        result.base_info.append((base, cs_name))
    return result


def _base_key(base: Dict[str, Optional[float]]) -> Tuple:
    """Hashable key grouping identical base positions (mm tolerance)."""
    def r(v: Optional[float]) -> Optional[int]:
        return None if v is None else round(v * 1000)

    return (r(base.get("easting")), r(base.get("northing")),
            r(base.get("elevation")), r(base.get("longitude")),
            r(base.get("latitude")), r(base.get("ellipsoidal_height")))


def _point_date(point: SurveyPoint) -> str:
    ts = point.averaging_start or point.averaging_end or ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", ts)
    return m.group(1) if m else "undated"


def build_project(points: List[SurveyPoint],
                  base_info: List[Tuple[Dict[str, Optional[float]], str]],
                  name: str,
                  source_file: str = "") -> Project:
    """Assemble parsed points into a :class:`Project`.

    Distinct base positions become :class:`BaseStation` records; points are
    grouped into :class:`RoverSession` objects split on (base, calendar day).
    """
    # --- base stations: one record per distinct base position ---
    base_ids: Dict[Tuple, str] = {}
    bases: List[BaseStation] = []
    for (base, _cs) in base_info:
        key = _base_key(base)
        if key not in base_ids:
            bid = f"BASE-{len(bases) + 1}"
            base_ids[key] = bid
            bases.append(BaseStation(
                id=bid,
                easting=base.get("easting"),
                northing=base.get("northing"),
                elevation=base.get("elevation"),
                longitude=base.get("longitude"),
                latitude=base.get("latitude"),
                ellipsoidal_height=base.get("ellipsoidal_height"),
                source="csv",
            ))

    # --- sessions: split on (base, day) ---
    sessions: Dict[Tuple[str, str], RoverSession] = {}
    order: List[Tuple[str, str]] = []
    cs_names = [cs for (_b, cs) in base_info if cs]
    for point, (base, _cs) in zip(points, base_info):
        key = _base_key(base)
        bid = base_ids.get(key)
        if bid is not None:
            for b in bases:
                if b.id == bid:
                    b.n_points += 1
        skey = (bid or "NOBASE", _point_date(point))
        if skey not in sessions:
            sid = f"{skey[1]}_{skey[0]}" if skey[1] != "undated" else skey[0]
            sessions[skey] = RoverSession(id=sid, base_station_id=bid,
                                          date=skey[1])
            order.append(skey)
        sessions[skey].points.append(point)

    crs = max(set(cs_names), key=cs_names.count) if cs_names else ""
    return Project(
        name=name,
        crs=crs,
        source_files=[source_file] if source_file else [],
        base_stations=bases,
        sessions=[sessions[k] for k in order],
    )


def import_emlid_csv(path: str, project_name: Optional[str] = None) -> Project:
    """Parse an Emlid CSV file straight into a :class:`Project`."""
    import os
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        result = parse_emlid_csv(fh)
    name = project_name or os.path.splitext(os.path.basename(path))[0]
    return build_project(result.points, result.base_info, name,
                         source_file=os.path.basename(path))
