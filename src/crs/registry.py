"""Registry loading and indexing over the checked-in EPSG data."""
from __future__ import annotations

from typing import Dict, List

from ._registry_data import REGISTRY
from .errors import UnknownEpsg
from .models import CrsEntry

_ENTRIES: List[CrsEntry] = [CrsEntry(**{k: v for k, v in r.items()}) for r in REGISTRY]
_BY_EPSG: Dict[int, CrsEntry] = {e.epsg: e for e in _ENTRIES}


def list_entries() -> List[CrsEntry]:
    """All registry entries, sorted by EPSG code."""
    return list(_ENTRIES)


def by_epsg(code: int) -> CrsEntry:
    """Return the registry entry for an EPSG code.

    Raises UnknownEpsg when the code is not registered.
    """
    try:
        return _BY_EPSG[int(code)]
    except (KeyError, TypeError, ValueError):
        raise UnknownEpsg("EPSG:%r is not in the survey-crs registry" % (code,))


def entries_for_kind(kind: str) -> List[CrsEntry]:
    return [e for e in _ENTRIES if e.kind == kind]


def entries_for_group(group: str) -> List[CrsEntry]:
    return [e for e in _ENTRIES if e.group == group]
