"""CRS picker API: search, by_epsg, zones_for_state, group_by_type, suggest."""
from __future__ import annotations

from typing import Dict, List, Optional

from . import registry
from .errors import UnknownState
from .models import CrsEntry

_STATE_ABBR = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico and Virgin Is.",
}
_STATE_BY_NAME = {v.lower(): v for v in _STATE_ABBR.values()}


def normalize_state(state: str) -> str:
    """Resolve a state name or postal abbreviation to the canonical name."""
    s = state.strip()
    if len(s) == 2 and s.upper() in _STATE_ABBR:
        return _STATE_ABBR[s.upper()]
    key = s.lower()
    if key in _STATE_BY_NAME:
        return _STATE_BY_NAME[key]
    raise UnknownState("unknown US state: %r" % (state,))


def by_epsg(code: int) -> CrsEntry:
    """Fetch one CRS by EPSG code (re-exported from the registry)."""
    return registry.by_epsg(code)


def search(query: str, limit: Optional[int] = None) -> List[CrsEntry]:
    """Case-insensitive token search over name, state, zone, EPSG, area.

    Every whitespace-separated token must appear in the entry's text;
    name matches rank before area-of-use matches; results are EPSG-sorted
    within each rank.
    """
    tokens = query.strip().lower().split()
    if not tokens:
        return []
    name_hits, other_hits = [], []
    for e in registry.list_entries():
        hay_name = " ".join([e.name, e.state or "", e.zone or "",
                             str(e.epsg)]).lower()
        if all(t in hay_name for t in tokens):
            name_hits.append(e)
        elif all(t in (e.area_name or "").lower() for t in tokens):
            other_hits.append(e)
    name_hits.sort(key=lambda e: e.epsg)
    other_hits.sort(key=lambda e: e.epsg)
    out = name_hits + other_hits
    return out[:limit] if limit else out


def zones_for_state(state: str) -> List[CrsEntry]:
    """All SPCS entries for a state (name or 2-letter abbreviation)."""
    canonical = normalize_state(state)
    return sorted(
        (e for e in registry.list_entries()
         if e.group == "spcs" and e.state == canonical),
        key=lambda e: e.epsg,
    )


def group_by_type() -> Dict[str, List[CrsEntry]]:
    """Registry grouped as {'spcs': [...], 'utm': [...], 'geographic': [...]},
    each EPSG-sorted."""
    return {
        "spcs": registry.entries_for_group("spcs"),
        "utm": registry.entries_for_group("utm"),
        "geographic": registry.entries_for_group("geographic"),
    }


def _in_bbox(lon: float, lat: float, bbox) -> bool:
    w, s, e_, n = bbox
    return w <= lon <= e_ and s <= lat <= n


def suggest(lat: float, lon: float,
            datum: str = "NAD83(2011)") -> List[CrsEntry]:
    """Suggest CRSs for a geographic position.

    Returns SPCS zones whose area of use contains the point (for the
    requested datum) first, then the WGS 84 UTM zone for the longitude.
    Empty list when nothing contains the point.
    """
    picks: List[CrsEntry] = []
    for e in registry.list_entries():
        if e.group == "spcs" and e.datum == datum and _in_bbox(lon, lat, e.bbox):
            picks.append(e)
    picks.sort(key=lambda e: e.epsg)
    if -80.0 <= lat <= 84.0:
        zone = int((lon + 180.0) // 6) + 1
        zone = min(max(zone, 1), 60)
        hemi = "N" if lat >= 0 else "S"
        epsg = (32600 if hemi == "N" else 32700) + zone
        utm = registry.by_epsg(epsg)
        if utm not in picks:
            picks.append(utm)
    return picks
