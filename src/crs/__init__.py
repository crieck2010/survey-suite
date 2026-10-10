"""survey-crs: CRS registry and coordinate transforms for the land-surveying suite.

Public API (stable for survey-field v0.2.0 / survey-suite v0.3.0):

  Picker
    by_epsg(code)            -> CrsEntry
    search(query, limit)     -> list[CrsEntry]
    zones_for_state(state)   -> list[CrsEntry]
    group_by_type()          -> {"spcs": [...], "utm": [...], "geographic": [...]}
    suggest(lat, lon, datum) -> list[CrsEntry]

  Transforms
    project(lat, lon, epsg, h=0.0)                 -> TransformResult
    unproject(x, y, epsg, h=0.0)                   -> TransformResult
    transform_coords(x, y, from_epsg, to_epsg, h=0.0) -> TransformResult
    datum_path(from_datum, to_datum)               -> DatumPath

  Units
    m_to_ftus, ftus_to_m, m_to_ft, ft_to_m, to_metres, from_metres
    US_FOOT_M (exactly 1200/3937)

Heights are ellipsoidal; v1 has no geoid / NAVD88 support.
"""
from __future__ import annotations

from .datums import DATUMS, datum_path
from .errors import (CrsError, DatumError, ProjectionError, UnknownEpsg,
                     UnknownState)
from .models import (CrsEntry, DatumPath, GeographicPoint, ProjectedPoint,
                     TransformResult)
from .picker import (by_epsg, group_by_type, search, suggest,
                     zones_for_state)
from .projections import backend_name
from .registry import list_entries
from .transforms import project, transform_coords, unproject
from .units import (INTL_FOOT_M, M_PER_US_FOOT, US_FOOT_M, from_metres,
                    ft_to_m, ftus_to_m, m_to_ft, m_to_ftus, to_metres)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "DATUMS",
    "CrsEntry", "DatumPath", "GeographicPoint", "ProjectedPoint",
    "TransformResult",
    "CrsError", "DatumError", "ProjectionError", "UnknownEpsg",
    "UnknownState",
    "by_epsg", "search", "zones_for_state", "group_by_type", "suggest",
    "list_entries",
    "project", "unproject", "transform_coords", "datum_path",
    "backend_name",
    "US_FOOT_M", "M_PER_US_FOOT", "INTL_FOOT_M",
    "m_to_ftus", "ftus_to_m", "m_to_ft", "ft_to_m",
    "to_metres", "from_metres",
]
