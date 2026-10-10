"""Adapters: shape survey-field jobs for the sibling engines.

These adapters return **plain data** (dicts / lists), never engine objects,
so survey-field keeps zero dependencies. The consumer imports its own engine
and splats the dicts in. Exact call shapes are shown in docs/INTEROP.md.

* :func:`to_cogo_kwargs` — kwargs for ``cogo.Point(northing, easting,
  name, elevation)`` from survey-cogo.
* :func:`to_adjust_control` — the ``fixed={name: elevation}`` mapping for
  ``adjust.adjust_level_net`` from survey-adjust, built from base stations.
* :func:`to_adjust_observations` — rover elevation differences as
  ``DiffObservation(from_station, to_station, delta_h, sigma)`` kwargs,
  observed base→rover with sigma from the point's elevation RMS.
* :func:`job_summary` — compact stats for the CLI and the desktop app.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import Project, Solution, SurveyPoint

#: RMS fallback (m) when a point has no recorded elevation RMS.
DEFAULT_SIGMA_M = 0.05


def to_cogo_kwargs(point: SurveyPoint) -> Optional[Dict[str, Any]]:
    """Return ``dict(northing, easting, name, elevation)`` for ``cogo.Point``.

    Returns ``None`` when the point has no projected coordinates (e.g. a
    geographic-CS export); the caller can reproject via survey-geodesy first.
    """
    if not point.has_projected():
        return None
    return {
        "northing": point.northing,
        "easting": point.easting,
        "name": point.name,
        "elevation": point.elevation if point.elevation is not None else 0.0,
    }


def project_cogo_points(project: Project) -> List[Dict[str, Any]]:
    """All points of the project as ``cogo.Point`` kwargs (projected only)."""
    out = []
    for point in project.iter_points():
        kwargs = to_cogo_kwargs(point)
        if kwargs is not None:
            out.append(kwargs)
    return out


def to_adjust_control(project: Project) -> Dict[str, float]:
    """Fixed-station mapping for ``adjust_level_net(observations, fixed=...)``.

    Base stations with a known elevation become held datum stations. Keys are
    base-station ids (``BASE-1`` …); build #2 may rename them onto the user's
    control-point naming.
    """
    fixed: Dict[str, float] = {}
    for base in project.base_stations:
        if base.elevation is not None:
            fixed[base.id] = base.elevation
    return fixed


def _point_sigma(point: SurveyPoint) -> float:
    if point.rms_u is not None and point.rms_u > 0:
        return point.rms_u
    if point.rms_lateral is not None and point.rms_lateral > 0:
        return point.rms_lateral
    return DEFAULT_SIGMA_M


def to_adjust_observations(project: Project) -> List[Dict[str, Any]]:
    """Rover elevations as ``DiffObservation`` kwargs (base → rover).

    Each FIX rover point with an elevation and a known-elevation base yields
    one elevation-difference observation ``delta_h = rover_elev - base_elev``
    with ``sigma`` from the point's elevation RMS (lateral RMS, then 5 cm
    fallback). FLOAT/SINGLE points are excluded — build #2 decides how to
    weight or reject them; the exclusion is recorded, not silent.
    """
    obs: List[Dict[str, Any]] = []
    for session in project.sessions:
        base = project.base_station(session.base_station_id)
        if base is None or base.elevation is None:
            continue
        for point in session.points:
            if point.solution != Solution.FIX:
                continue
            if point.elevation is None:
                continue
            obs.append({
                "from_station": base.id,
                "to_station": point.name,
                "delta_h": point.elevation - base.elevation,
                "sigma": _point_sigma(point),
                "excluded_reason": None,
            })
    return obs


def job_summary(project: Project) -> Dict[str, Any]:
    """Compact stats: sessions, solution mix, coordinate coverage."""
    solutions: Dict[str, int] = {}
    n_projected = 0
    n_geographic = 0
    for point in project.iter_points():
        solutions[point.solution] = solutions.get(point.solution, 0) + 1
        if point.has_projected():
            n_projected += 1
        if point.has_geographic():
            n_geographic += 1
    return {
        "name": project.name,
        "crs": project.crs,
        "n_base_stations": len(project.base_stations),
        "n_sessions": len(project.sessions),
        "n_points": project.n_points(),
        "n_projected": n_projected,
        "n_geographic": n_geographic,
        "solutions": solutions,
        "sessions": [
            {"id": s.id, "base_station_id": s.base_station_id,
             "date": s.date, "n_points": len(s.points)}
            for s in project.sessions
        ],
    }
