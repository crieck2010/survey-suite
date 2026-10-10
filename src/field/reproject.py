"""Optional CRS reprojection for the import step (survey-crs backend).

``field import --target-crs <name|EPSG>`` reprojects a geographic-CS Emlid
export into a projected CRS on import. ``survey-crs`` is an **optional**
dependency: it is imported lazily here, and every failure mode raises
:class:`CrsReprojectError` with an actionable message -- never a bare
``ImportError`` traceback.

Conservative v1 rules (documented in docs/INTEROP.md):

* Geographic CSV + explicit target -> every point's longitude/latitude is
  transformed into the target CRS (easting/northing filled in, project CRS
  set to the target, provenance recorded).
* Projected CSV + target that resolves to the *same* EPSG -> no-op with an
  informational note (provenance still recorded, ``applied: false``).
* Projected CSV + a *different* explicit target -> loud refusal. Reprojecting
  between projected CRSs is not supported in v1; re-export the CSV in the
  target CRS or in a geographic CS and re-import.
* Projected CSV + explicit target but the CSV's CS name cannot be mapped to
  the survey-crs registry -> loud refusal (the target cannot be verified
  against an unknown source, so mixing is not attempted).

Datum shifts between distinct datums are survey-crs null approximations
(e.g. NAD83(2011) <-> WGS 84 ~2 m in CONUS). Every transform result carries
accuracy metadata and warnings; this module records them in the job file's
``crs_provenance`` block and returns them on the report so the CLI can
surface them in the import report. Never present a shifted coordinate as
survey control without surfacing the warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .models import Project

#: Matches "EPSG:6539", "epsg: 6539", or a bare "6539".
_EPSG_RE = re.compile(r"^\s*(?:epsg\s*:\s*)?(\d{1,6})\s*$", re.IGNORECASE)

#: Embedded "EPSG:nnnn" inside a longer CS-name string.
_EPSG_EMBEDDED_RE = re.compile(r"epsg\s*:\s*(\d{1,6})", re.IGNORECASE)


class CrsReprojectError(Exception):
    """Clean, actionable CRS failure: missing backend, unresolvable CRS, or
    a refused projected->projected mix. The CLI turns this into ``error: ...``
    on stderr with exit 1 (no job file written)."""


def _import_crs():
    """Lazily import the optional survey-crs engine."""
    try:
        import crs  # type: ignore[import-not-found]
    except ImportError:
        raise CrsReprojectError(
            "CRS reprojection needs the survey-crs engine, which is not "
            "installed. Install it with:\n"
            "    pip install survey-crs\n"
            "(https://github.com/crieck2010/survey-crs) and re-run the import."
        )
    return crs


def _unknown_epsg_hint(code: int) -> str:
    hint = ("The survey-crs registry carries NAD83(2011) SPCS, WGS 84 UTM, "
            "and geographic entries -- not legacy NAD83(1986) codes.")
    if code == 2263:
        hint += (" Did you mean EPSG:6539, 'NAD83(2011) / New York Long Island "
                 "(ftUS)'? Note the ~1 m datum difference between NAD83(1986) "
                 "and NAD83(2011); do not substitute blindly.")
    return hint


def resolve_target(spec: str, crs_mod=None):
    """Resolve a ``--target-crs`` spec to a survey-crs registry entry.

    Accepts ``"EPSG:6539"``, ``"6539"``, or a registry name / picker query
    (e.g. ``"New York Long Island (ftUS)"``). Raises :class:`CrsReprojectError`
    when the spec is unknown or ambiguous.
    """
    crs_mod = crs_mod or _import_crs()
    spec = (spec or "").strip()
    if not spec:
        raise CrsReprojectError("--target-crs needs a value, e.g. --target-crs EPSG:6539")

    m = _EPSG_RE.match(spec)
    if m:
        code = int(m.group(1))
        try:
            return crs_mod.by_epsg(code)
        except Exception as exc:  # UnknownEpsg
            raise CrsReprojectError(
                f"unknown --target-crs {spec!r}: {exc}. {_unknown_epsg_hint(code)}"
            )

    hits = crs_mod.search(spec)
    if not hits:
        raise CrsReprojectError(
            f"unknown --target-crs {spec!r}: no survey-crs registry entry matches. "
            "Try an EPSG code (e.g. --target-crs EPSG:6539) or install the "
            "survey-crs CLI and run: crs search '<query>'"
        )
    lowered = spec.lower()
    for hit in hits:
        if hit.name.lower() == lowered:
            return hit  # exact registry-name match wins over partial hits
    if len(hits) == 1:
        return hits[0]
    shown = ", ".join(f"{h.name} (EPSG:{h.epsg})" for h in hits[:5])
    raise CrsReprojectError(
        f"ambiguous --target-crs {spec!r}: matches {len(hits)} registry entries "
        f"({shown}{' ...' if len(hits) > 5 else ''}). "
        "Disambiguate with an EPSG code, e.g. --target-crs EPSG:6539"
    )


def _exact_name(name: str, crs_mod):
    """Registry entry whose official name matches exactly (case-insensitive)."""
    lowered = name.strip().lower()
    for hit in crs_mod.search(name):
        if hit.name.lower() == lowered:
            return hit
    return None


def resolve_source(cs_name: str, points_are_projected: bool,
                   crs_mod=None) -> Tuple[Optional[Any], str]:
    """Map the CSV's majority-vote CS name to a survey-crs registry entry.

    Returns ``(entry, note)``; ``entry`` is ``None`` when the CS name cannot
    be mapped, in which case the caller refuses loudly for an explicit
    target. ``note`` is an informational string for the import report ("" when
    the mapping was direct).
    """
    crs_mod = crs_mod or _import_crs()
    cs_name = (cs_name or "").strip()

    if not cs_name:
        if points_are_projected:
            return None, ""
        entry = crs_mod.by_epsg(4326)  # WGS 84 geographic
        note = ("assumed source CRS WGS 84 (EPSG:4326): the CSV recorded no CS "
                "name and carries geographic coordinates (Emlid receivers log "
                "natively in WGS 84)")
        return entry, note

    m = _EPSG_EMBEDDED_RE.search(cs_name)
    if m:
        try:
            return crs_mod.by_epsg(int(m.group(1))), ""
        except Exception:
            return None, ""

    entry = _exact_name(cs_name, crs_mod)
    if entry is not None:
        return entry, ""

    hits = crs_mod.search(cs_name)
    if len(hits) == 1:
        return hits[0], f"matched CS name {cs_name!r} to registry entry '{hits[0].name}' via search"

    # Geographic keyword fallback for plain datum names ("WGS 84", "NAD83(2011)").
    lowered = cs_name.lower()
    if not points_are_projected:
        if "wgs" in lowered:
            return crs_mod.by_epsg(4326), f"mapped CS name {cs_name!r} to WGS 84 (EPSG:4326)"
        if "cors96" in lowered:
            return crs_mod.by_epsg(6783), f"mapped CS name {cs_name!r} to NAD83(CORS96) (EPSG:6783)"
        if "nad83(2011)" in lowered or "nad 83(2011)" in lowered:
            return crs_mod.by_epsg(6318), f"mapped CS name {cs_name!r} to NAD83(2011) (EPSG:6318)"
    return None, ""


def _entry_summary(entry) -> Dict[str, Any]:
    return {"name": entry.name, "epsg": entry.epsg,
            "datum": entry.datum, "unit": entry.unit}


def _build_provenance(source, target, crs_mod, applied: bool, n_points: int,
                      warnings: List[str], notes: List[str],
                      source_raw: str) -> Dict[str, Any]:
    """The ``crs_provenance`` block written onto the project."""
    path = crs_mod.datum_path(source.datum, target.datum)
    return {
        "source_crs": {**_entry_summary(source), "as_recorded_in_csv": source_raw},
        "target_crs": _entry_summary(target),
        "transform": {
            "applied": applied,
            "n_points": n_points,
            "survey_crs_version": crs_mod.__version__,
            "backend": crs_mod.backend_name(),
            "datum_path": {
                "from_datum": path.from_datum,
                "to_datum": path.to_datum,
                "method": path.method,
                "accuracy_horizontal_m": path.accuracy_horizontal_m,
                "region": path.region,
                "source": path.source,
                "warning": path.warning,
            },
            "warnings": list(warnings),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "notes": list(notes),
    }


@dataclass
class ReprojectReport:
    """Outcome of :func:`reproject_project` for the CLI import report."""

    applied: bool
    n_points: int
    source_name: str
    target_name: str
    notes: List[str] = dc_field(default_factory=list)
    warnings: List[str] = dc_field(default_factory=list)
    provenance: Dict[str, Any] = dc_field(default_factory=dict)


def reproject_project(project: Project, target_spec: str) -> ReprojectReport:
    """Apply ``--target-crs`` to an imported project (mutates in place).

    Geographic points are transformed into the target CRS; the project CRS
    is set to the target's registry name and a ``crs_provenance`` block is
    recorded. RMS, solution, antenna, and timing metadata are untouched.
    Base-station coordinates are *not* reprojected in v0.2.0 (documented
    limitation).

    Raises :class:`CrsReprojectError` for a missing survey-crs install, an
    unresolvable target or source CRS, inconsistent CSV coordinates, or a
    projected->projected CRS mix (loud refusal, never silent).
    """
    crs_mod = _import_crs()
    target = resolve_target(target_spec, crs_mod)

    points = list(project.iter_points())
    any_projected = any(p.has_projected() for p in points)
    any_geographic = any(p.has_geographic() for p in points)
    source_raw = project.crs or ""
    source, source_note = resolve_source(source_raw, any_projected, crs_mod)
    notes = [source_note] if source_note else []

    if source is None:
        raise CrsReprojectError(
            f"cannot map the CSV's coordinate system {source_raw!r} to a "
            "survey-crs registry entry, so --target-crs "
            f"{target_spec!r} cannot be verified. Refusing to proceed rather "
            "than risk mixing coordinate systems. (v0.2.0 rule: the CSV's "
            "source CRS must be resolvable when --target-crs is given.)"
        )

    if source.epsg == target.epsg:
        provenance = _build_provenance(
            source, target, crs_mod, applied=False, n_points=0,
            warnings=[], source_raw=source_raw,
            notes=notes + [f"points already in {target.name} (EPSG:{target.epsg}); "
                           "no transform applied"])
        project.crs_provenance = provenance
        return ReprojectReport(
            applied=False, n_points=0, source_name=source.name,
            target_name=target.name,
            notes=[f"already in {target.name} (EPSG:{target.epsg}): no transform applied"],
            provenance=provenance)

    if any_projected:
        raise CrsReprojectError(
            f"refusing: the CSV is projected in '{source.name}' (EPSG:{source.epsg}) "
            f"but --target-crs requests '{target.name}' (EPSG:{target.epsg}). "
            "survey-field v0.2.0 does not transform between projected CRSs "
            "(conservative v1 rule) -- re-export the CSV in the target CRS or "
            "in a geographic CS and re-import."
        )

    if source.is_projected:
        raise CrsReprojectError(
            f"inconsistent CSV: the CS name {source_raw!r} resolves to projected "
            f"'{source.name}' but no point carries easting/northing. Refusing "
            "to guess; check the export's coordinate system."
        )

    if not any_geographic:
        raise CrsReprojectError(
            "no geographic coordinates to reproject: no point carries "
            "longitude/latitude. (--target-crs needs a geographic-CS export.)"
        )

    warnings: List[str] = []
    n = 0
    for point in points:
        if not point.has_geographic():
            continue
        h = point.ellipsoidal_height if point.ellipsoidal_height is not None else 0.0
        result = crs_mod.transform_coords(
            point.longitude, point.latitude, source.epsg, target.epsg, h=h)
        point.easting = result.x
        point.northing = result.y
        # Elevation, RMS, solution, antenna height, and timing metadata are
        # deliberately untouched: the transform only moves horizontal position.
        n += 1
        for w in result.warnings:
            if w not in warnings:
                warnings.append(w)

    project.crs = target.name
    notes.append(f"reprojected {n} point(s) from {source.name} (EPSG:{source.epsg}) "
                 f"to {target.name} (EPSG:{target.epsg})")
    provenance = _build_provenance(
        source, target, crs_mod, applied=True, n_points=n,
        warnings=warnings, notes=notes, source_raw=source_raw)
    project.crs_provenance = provenance
    return ReprojectReport(
        applied=True, n_points=n, source_name=source.name,
        target_name=target.name, notes=notes, warnings=warnings,
        provenance=provenance)
