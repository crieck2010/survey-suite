"""Handoff adapters: figures -> survey-drafting / survey-cogo.

Both adapters consume plain interchange dicts (as returned by
:func:`interchange.read_figures`); neither imports the peer engine at
module load. The drafting adapter emits the plain-dict entity contract
from ``survey-drafting`` (``docs/INTEROP.md``); the cogo adapter imports
``cogo`` lazily and fails with an actionable message when it is missing.

Coordinate note: drafting entities are (x, y) tuples in world metres,
so a figure vertex (easting, northing) becomes ``(easting, northing)``.
survey-drafting has no arc entity type, so arcs are emitted as chorded
polylines within ``chord_sagitta_m`` (documented, configurable).
"""

from __future__ import annotations

from typing import Dict, List

from .errors import LineworkError
from .figures import Figure
from .interchange import load_figures


def _as_figures(data: dict) -> List[Figure]:
    load_figures(data)
    return [Figure.from_dict(f) for f in data.get("figures", [])]


def figures_to_drafting_layers(data: dict, chord_sagitta_m: float = 0.01,
                               include_points: bool = True
                               ) -> Dict[str, List[dict]]:
    """Emit figures as survey-drafting layer entities.

    Returns ``{layer_name: [entity, ...]}``. Open figures become
    ``{"type": "line", "pts": [(x, y), ...]}``; closed figures become
    ``{"type": "polygon", "pts": [...], "hatch": False}``. Figures land
    on their prefix-database target layer (default ``"linework"``).
    With ``include_points``, each coded point becomes
    ``{"type": "point", "at": (x, y), "label": ...}`` on its
    description-key layer (default ``"points"``).
    """
    if chord_sagitta_m <= 0:
        raise LineworkError("chord_sagitta_m must be positive")
    layers: Dict[str, List[dict]] = {}
    for fig in _as_figures(data):
        pts = [(e, n) for e, n in fig.chorded_points(chord_sagitta_m)]
        if len(pts) < 2:
            continue  # degenerate; the builder already refused these
        if fig.closed:
            entity = {"type": "polygon", "pts": pts, "hatch": False}
        else:
            entity = {"type": "line", "pts": pts}
        layers.setdefault(fig.layer, []).append(entity)
    if include_points:
        for p in data.get("points", []):
            if p.get("easting") is None or p.get("northing") is None:
                continue
            layers.setdefault(p.get("layer") or "points", []).append({
                "type": "point",
                "at": (p["easting"], p["northing"]),
                "label": p.get("label", p.get("name", "")),
            })
    return layers


def figures_to_cogo(data: dict, chord_sagitta_m: float = 0.01
                    ) -> Dict[str, list]:
    """Emit figures as ``cogo.Point`` lists, keyed by figure id.

    Each list is the chorded vertex run (closed figures repeat the first
    point at the end), ready for ``cogo.polygon_area`` /
    ``cogo.polygon_perimeter`` / ``cogo.inverse``. Raises LineworkError
    with an install hint when survey-cogo is not importable.
    """
    try:
        from cogo import Point as CogoPoint
    except ImportError as exc:
        raise LineworkError(
            "figures_to_cogo needs the survey-cogo engine "
            "(pip install git+https://github.com/crieck2010/survey-cogo)") \
            from exc
    if chord_sagitta_m <= 0:
        raise LineworkError("chord_sagitta_m must be positive")
    out: Dict[str, list] = {}
    for fig in _as_figures(data):
        pts3d = fig.chorded_points_3d(chord_sagitta_m)
        out[fig.id] = [
            CogoPoint(northing=n, easting=e, name=f"{fig.id}.{k}",
                      elevation=(el if el is not None else 0.0))
            for k, (e, n, el) in enumerate(pts3d)
        ]
    return out
