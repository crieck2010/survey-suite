"""Figure builder: coded points in collection order -> figure objects.

Traversal order (documented contract): the job's sessions are visited in
file order; within each session, points are visited in row order (this is
exactly the order survey-field's ``parse_emlid_csv`` collected them --
sessions split on (base, day), lists round-trip in order). Figure identity
is global across sessions: a figure begun on day 1 and continued on day 2
under the same base code is one figure.

Fail-loud rules (raise :class:`FigureBuildError`, never silently drop):
    * end / continue / close / offset / curve token with no open figure
    * begin while the figure is already open
    * a base code matching neither the figure-prefix DB nor any
      description key (unknown code, with did-you-mean suggestions)
    * a coded point with no easting/northing
    * a figure ended with fewer than 2 vertices
    * a curve begun but never ended, an end-curve with no matching
      begin-curve, a curve span with zero or multiple intermediate points
    * a radius parameter that is missing, non-numeric, or smaller than
      half the chord; a three-point span through collinear points
    * an unrecognised control field (from the code-set parser)

Non-fatal conditions are *flags* on the figure and in the build report:
``unclosed_expected_closed``, ``closure_exceeds_tolerance``,
``figure_never_ended``. ``linework build --strict`` turns flags into a
non-zero exit.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .codeset import LineworkCodeSet, NEEDS_OPEN
from .errors import FigureBuildError, LineworkError
from .geometry import (
    chord_arc,
    circle_from_3_points,
    misclosure_m,
    offset_polyline,
    radius_arc,
    three_point_arc,
)
from .keys import DescriptionKeys
from .prefixes import FigurePrefix, FigurePrefixDB

XY = Tuple[float, float]


@dataclass
class FigureVertex:
    name: str
    easting: float
    northing: float
    elevation: Optional[float] = None

    def xy(self) -> XY:
        return (self.easting, self.northing)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "easting": self.easting,
                "northing": self.northing, "elevation": self.elevation}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FigureVertex":
        return cls(name=d["name"], easting=d["easting"],
                   northing=d["northing"], elevation=d.get("elevation"))


@dataclass
class ArcSpan:
    """One resolved arc: vertex indices plus circle parameters."""
    start_idx: int
    end_idx: int
    mode: str                      # "3pt" | "radius"
    center_e: float
    center_n: float
    radius: float
    turn: str                      # "left" | "right" (traveller's steering)

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": "arc", "from": self.start_idx, "to": self.end_idx,
                "mode": self.mode, "center": [self.center_e, self.center_n],
                "radius": self.radius, "turn": self.turn}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArcSpan":
        c = d["center"]
        return cls(start_idx=d["from"], end_idx=d["to"], mode=d.get("mode", "?"),
                   center_e=c[0], center_n=c[1],
                   radius=d["radius"], turn=d["turn"])


@dataclass
class Figure:
    """One resolved figure: ordered vertices + line/arc segments."""

    id: str
    base_code: str
    prefix: str
    layer: str = "linework"
    style: str = "solid"
    vertices: List[FigureVertex] = dc_field(default_factory=list)
    arc_spans: List[ArcSpan] = dc_field(default_factory=list)
    closed: bool = False
    close_method: str = "none"          # "explicit" | "auto" | "offset" | "none"
    misclosure_m: Optional[float] = None
    flags: List[Dict[str, str]] = dc_field(default_factory=list)
    offset_of: Optional[str] = None
    offset_m: Optional[float] = None
    provenance: Dict[str, Any] = dc_field(default_factory=dict)

    @property
    def source_points(self) -> List[str]:
        return [v.name for v in self.vertices]

    def segments(self) -> List[Dict[str, Any]]:
        """Line/arc segment list spanning the vertices in order."""
        spans = {s.start_idx: s for s in self.arc_spans}
        segs: List[Dict[str, Any]] = []
        i = 0
        n = len(self.vertices)
        while i < n - 1:
            if i in spans:
                segs.append(spans[i].to_dict())
                i = spans[i].end_idx
            else:
                segs.append({"kind": "line", "from": i, "to": i + 1})
                i += 1
        return segs

    def chorded_points_3d(self, max_sagitta_m: float) -> List[Tuple[float, float, Optional[float]]]:
        """Chorded (easting, northing, elevation) polyline of the figure.

        Arcs become chord polylines within ``max_sagitta_m``; elevations
        are linearly interpolated along chords. A closed figure repeats
        its first point at the end.
        """
        spans = {s.start_idx: s for s in self.arc_spans}
        out: List[Tuple[float, float, Optional[float]]] = []
        i = 0
        n = len(self.vertices)
        while i < n - 1:
            v0 = self.vertices[i]
            if i in spans:
                s = spans[i]
                v1 = self.vertices[s.end_idx]
                import math as _m
                a0 = _m.atan2(v0.easting - s.center_e, v0.northing - s.center_n)
                a1 = _m.atan2(v1.easting - s.center_e, v1.northing - s.center_n)
                chord = chord_arc((s.center_e, s.center_n), s.radius,
                                  a0, a1, s.turn, max_sagitta_m)
                # Interpolate elevation along the chord count.
                m = len(chord) - 1
                for k, (e, nn) in enumerate(chord):
                    if k == 0 and out:
                        continue  # joint already emitted
                    t = k / m if m else 0.0
                    if v0.elevation is None or v1.elevation is None:
                        elev = v0.elevation if k < m else v1.elevation
                        if v0.elevation is None and v1.elevation is None:
                            elev = None
                    else:
                        elev = v0.elevation + t * (v1.elevation - v0.elevation)
                    out.append((e, nn, elev))
                i = s.end_idx
            else:
                v1 = self.vertices[i + 1]
                if not out:
                    out.append((v0.easting, v0.northing, v0.elevation))
                out.append((v1.easting, v1.northing, v1.elevation))
                i += 1
        if self.closed and out:
            first = self.vertices[0]
            out.append((first.easting, first.northing, first.elevation))
        return out

    def chorded_points(self, max_sagitta_m: float) -> List[XY]:
        return [(e, n) for e, n, _ in self.chorded_points_3d(max_sagitta_m)]

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "base_code": self.base_code,
            "prefix": self.prefix,
            "layer": self.layer,
            "style": self.style,
            "closed": self.closed,
            "close_method": self.close_method,
            "misclosure_m": (None if self.misclosure_m is None
                             else round(self.misclosure_m, 4)),
            "flags": list(self.flags),
            "vertices": [v.to_dict() for v in self.vertices],
            "segments": self.segments(),
            "source_points": self.source_points,
            "offset_of": self.offset_of,
            "offset_m": self.offset_m,
            "provenance": dict(self.provenance),
        }
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Figure":
        segs = d.get("segments", [])
        spans = [ArcSpan.from_dict(s) for s in segs if s.get("kind") == "arc"]
        return cls(
            id=d["id"], base_code=d.get("base_code", d["id"]),
            prefix=d.get("prefix", ""), layer=d.get("layer", "linework"),
            style=d.get("style", "solid"),
            vertices=[FigureVertex.from_dict(v) for v in d.get("vertices", [])],
            arc_spans=spans, closed=bool(d.get("closed", False)),
            close_method=d.get("close_method", "none"),
            misclosure_m=d.get("misclosure_m"),
            flags=list(d.get("flags", [])),
            offset_of=d.get("offset_of"), offset_m=d.get("offset_m"),
            provenance=dict(d.get("provenance", {})),
        )


@dataclass
class _CurveState:
    mode: str            # "3pt" | "radius"
    start_idx: int
    start_name: str
    radius: Optional[float] = None


@dataclass
class _OpenFigure:
    base: str
    prefix: FigurePrefix
    implicit: bool
    vertices: List[FigureVertex] = dc_field(default_factory=list)
    curve: Optional[_CurveState] = None
    arc_spans: List[ArcSpan] = dc_field(default_factory=list)
    offset_m: Optional[float] = None
    close_requested: bool = False


@dataclass
class PointRecord:
    """One job point with its resolved description key."""

    name: str
    code: str
    base_code: str
    easting: Optional[float]
    northing: Optional[float]
    elevation: Optional[float]
    layer: str
    symbol: str
    label: str
    figure: Optional[str]
    uncoded: bool

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "code": self.code,
                "base_code": self.base_code, "easting": self.easting,
                "northing": self.northing, "elevation": self.elevation,
                "layer": self.layer, "symbol": self.symbol,
                "label": self.label, "figure": self.figure,
                "uncoded": self.uncoded}


@dataclass
class BuildResult:
    figures: List[Figure] = dc_field(default_factory=list)
    points: List[PointRecord] = dc_field(default_factory=list)
    flags: List[Dict[str, str]] = dc_field(default_factory=list)
    warnings: List[str] = dc_field(default_factory=list)
    job_meta: Dict[str, Any] = dc_field(default_factory=dict)
    codeset_meta: Dict[str, str] = dc_field(default_factory=dict)

    def counts(self) -> Dict[str, int]:
        coded = sum(1 for p in self.points if not p.uncoded)
        return {
            "n_points": len(self.points),
            "n_coded_points": coded,
            "n_uncoded_points": len(self.points) - coded,
            "n_figures": len(self.figures),
            "n_closed_figures": sum(1 for f in self.figures if f.closed),
            "n_open_figures": sum(1 for f in self.figures if not f.closed),
            "n_offset_figures": sum(1 for f in self.figures if f.offset_of),
            "n_flags": len(self.flags),
        }


class FigureBuilder:
    """State machine: coded points in order -> figures."""

    def __init__(self, codeset: LineworkCodeSet, keys: DescriptionKeys,
                 prefixes: FigurePrefixDB,
                 offset_chord_sagitta_m: float = 0.01) -> None:
        self.codeset = codeset
        self.keys = keys
        self.prefixes = prefixes
        if offset_chord_sagitta_m <= 0:
            raise FigureBuildError("offset_chord_sagitta_m must be positive")
        self.offset_chord_sagitta_m = offset_chord_sagitta_m
        self._open: Dict[str, _OpenFigure] = {}
        self._result = BuildResult()
        self._figure_index = 0

    # -- public ------------------------------------------------------------
    def build(self, project: Any, job_sha256: str = "") -> BuildResult:
        """Build figures from a survey-field Project (duck-typed).

        ``project`` needs ``.sessions`` (in file order), each with
        ``.points`` (in row order) carrying ``.name/.code/.easting/
        .northing/.elevation``.
        """
        self._result.job_meta = {
            "name": getattr(project, "name", ""),
            "sha256": job_sha256,
            "crs": getattr(project, "crs", ""),
            "n_sessions": len(getattr(project, "sessions", [])),
        }
        self._result.codeset_meta = {
            "name": self.codeset.name, "version": self.codeset.version}
        sessions = getattr(project, "sessions", [])
        for session in sessions:
            for pt in getattr(session, "points", []):
                self._process_point(pt)
        for base in list(self._open):
            self._finalize(base, self._open[base], ended_how="never_ended")
        return self._result

    # -- per-point processing ----------------------------------------------
    def _process_point(self, pt: Any) -> None:
        name = str(getattr(pt, "name", ""))
        raw = str(getattr(pt, "code", "") or "")
        easting = getattr(pt, "easting", None)
        northing = getattr(pt, "northing", None)
        elevation = getattr(pt, "elevation", None)

        if not raw.strip():
            # Uncoded point: default description key, joins no figure.
            # Documented behaviour, counted in the report -- never silent.
            key = self.keys.default
            label = self.keys.render_label(key, {
                "name": name, "code": "", "easting": easting,
                "northing": northing, "elevation": elevation})
            self._result.points.append(PointRecord(
                name=name, code="", base_code="", easting=easting,
                northing=northing, elevation=elevation, layer=key.layer,
                symbol=key.symbol, label=label, figure=None, uncoded=True))
            return

        parsed = self.codeset.parse_code(raw)  # fail loud on bad fields
        base = parsed.base
        kinds = [c.kind for c in parsed.controls]
        by_kind = {c.kind: c for c in parsed.controls}

        if easting is None or northing is None:
            raise FigureBuildError(
                f"point {name!r} carries code {raw!r} but has no "
                "easting/northing; coded points must have coordinates")

        key = self.keys.match(base)
        prefix = self.prefixes.match(base)
        if prefix is None:
            raise FigureBuildError(self._unknown_code_msg(name, raw, base))

        fig = self._open.get(base)
        if "begin" in kinds:
            if fig is not None:
                raise FigureBuildError(
                    f"point {name!r}: figure {base!r} is already open; "
                    f"begin code {raw!r} starts it again -- end the open "
                    "figure first")
            fig = _OpenFigure(base=base, prefix=prefix, implicit=False)
            self._open[base] = fig
        if fig is None:
            # No open strand: fail loud, or implicit begin (automatic
            # linework, Civil 3D style). Curve *begins* are begin-like:
            # the BCV shot doubles as the figure's first point.
            offender = next((k for k in
                             ("end_curve_3pt", "end_curve_radius",
                              "continue", "end", "close", "offset")
                             if k in kinds), None)
            if offender is not None:
                raise FigureBuildError(
                    f"{NEEDS_OPEN[offender]}: point {name!r} (code {raw!r}) "
                    f"applies {offender.replace('_', ' ')} to figure {base!r} "
                    f"but no figure {base!r} is open")
            if self.codeset.auto_begin:
                fig = _OpenFigure(base=base, prefix=prefix, implicit=True)
                self._open[base] = fig
            else:
                raise FigureBuildError(
                    f"point {name!r}: no open figure for base code {base!r} "
                    f"(code {raw!r}); shoot a begin code first or enable "
                    "'auto_begin' in the code set")

        # Every coded point that belongs to a figure is one vertex.
        fig.vertices.append(FigureVertex(
            name=name, easting=float(easting), northing=float(northing),
            elevation=(None if elevation is None else float(elevation))))
        idx = len(fig.vertices) - 1

        # Curve begins / ends (before offset/close/end on the same point).
        if "begin_curve_3pt" in kinds:
            self._curve_begin(fig, name, raw, "3pt", None)
        if "begin_curve_radius" in kinds:
            param = by_kind["begin_curve_radius"].param
            if not param:
                raise FigureBuildError(
                    f"point {name!r}: radius-mode curve begin (code {raw!r}) "
                    "needs a radius parameter, e.g. '*bcr R=50'")
            radius = self.codeset.radius_param(param, raw)
            self._curve_begin(fig, name, raw, "radius", radius)
        if "end_curve_3pt" in kinds:
            self._curve_end(fig, name, raw, "3pt", idx)
        if "end_curve_radius" in kinds:
            self._curve_end(fig, name, raw, "radius", idx)

        if "offset" in kinds:
            param = by_kind["offset"].param
            if not param:
                raise FigureBuildError(
                    f"point {name!r}: offset code {raw!r} needs a distance, "
                    "e.g. '*off +0.6' (positive = right of travel)")
            if fig.offset_m is not None:
                raise FigureBuildError(
                    f"point {name!r}: figure {base!r} already has an offset "
                    "request; v0.1 supports one offset per figure")
            fig.offset_m = self.codeset.offset_param(param, raw)

        if "close" in kinds:
            fig.close_requested = True

        label = self.keys.render_label(key, {
            "name": name, "code": raw, "easting": easting,
            "northing": northing, "elevation": elevation})
        self._result.points.append(PointRecord(
            name=name, code=raw, base_code=base, easting=float(easting),
            northing=float(northing),
            elevation=(None if elevation is None else float(elevation)),
            layer=key.layer, symbol=key.symbol, label=label,
            figure=base, uncoded=False))

        # Close implies end; end finalizes the figure.
        if "close" in kinds or "end" in kinds:
            self._finalize(base, fig,
                           ended_how=("close" if "close" in kinds else "end"))

    # -- curves --------------------------------------------------------------
    def _curve_begin(self, fig: _OpenFigure, name: str, raw: str,
                     mode: str, radius: Optional[float]) -> None:
        if fig.curve is not None:
            raise FigureBuildError(
                f"point {name!r}: curve begin (code {raw!r}) while a curve "
                f"begun at point {fig.curve.start_name!r} is still open; "
                "end the open curve first")
        fig.curve = _CurveState(mode=mode,
                                start_idx=len(fig.vertices) - 1,
                                start_name=name, radius=radius)

    def _curve_end(self, fig: _OpenFigure, name: str, raw: str,
                   mode: str, idx: int) -> None:
        cur = fig.curve
        if cur is None:
            raise FigureBuildError(
                f"point {name!r}: end-curve (code {raw!r}) with no open "
                f"curve on figure {fig.base!r}")
        if cur.mode != mode:
            raise FigureBuildError(
                f"point {name!r}: end-curve mode {mode!r} does not match the "
                f"open {cur.mode!r} curve begun at point {cur.start_name!r}")
        n_mid = idx - cur.start_idx - 1
        if n_mid < 1:
            raise FigureBuildError(
                f"point {name!r}: curve on figure {fig.base!r} has no "
                "intermediate point between begin and end; a curve needs "
                "begin, at least one mid shot, end")
        if n_mid > 1:
            raise FigureBuildError(
                f"point {name!r}: curve on figure {fig.base!r} has "
                f"{n_mid} intermediate points; v0.1 resolves one arc per "
                "begin/end pair -- split the curve into multiple arcs")
        v0 = fig.vertices[cur.start_idx]
        vm = fig.vertices[cur.start_idx + 1]
        v1 = fig.vertices[idx]
        p0, pm, p1 = v0.xy(), vm.xy(), v1.xy()
        try:
            if mode == "3pt":
                center, radius, turn = three_point_arc(p0, pm, p1)
            else:
                assert cur.radius is not None
                center, radius, turn = radius_arc(p0, pm, p1, cur.radius)
        except LineworkError as exc:
            # Geometry failures -> fail loud with the field context.
            raise FigureBuildError(
                f"point {name!r}: cannot resolve curve on figure "
                f"{fig.base!r} ({cur.start_name!r} -> {vm.name!r} -> "
                f"{name!r}): {exc}") from exc
        fig.arc_spans.append(ArcSpan(
            start_idx=cur.start_idx, end_idx=idx, mode=mode,
            center_e=center[0], center_n=center[1],
            radius=radius, turn=turn))
        fig.curve = None

    # -- finalization ----------------------------------------------------------
    def _finalize(self, base: str, fig: _OpenFigure, ended_how: str) -> None:
        if fig.curve is not None:
            raise FigureBuildError(
                f"figure {base!r}: curve begun at point "
                f"{fig.curve.start_name!r} was never ended")
        if len(fig.vertices) < 2:
            raise FigureBuildError(
                f"figure {base!r} has only {len(fig.vertices)} vertex/vertices; "
                "a figure needs at least 2 points")
        pfx = fig.prefix
        first, last = fig.vertices[0], fig.vertices[-1]
        misclosure = misclosure_m(first.xy(), last.xy())

        closed = False
        close_method = "none"
        if ended_how == "close":
            closed, close_method = True, "explicit"
        elif ended_how == "end" and pfx.auto_close:
            closed, close_method = True, "auto"

        flags: List[Dict[str, str]] = []
        if closed and misclosure > pfx.closure_tolerance_m:
            flags.append({"flag": "closure_exceeds_tolerance",
                          "detail": f"misclosure {misclosure:.3f} m exceeds "
                                    f"tolerance {pfx.closure_tolerance_m} m"})
        if not closed and pfx.expect_closed:
            flags.append({"flag": "unclosed_expected_closed",
                          "detail": f"figure {base!r} was expected to close "
                                    f"(prefix {pfx.prefix!r}) but ended open"})
        if ended_how == "never_ended":
            flags.append({"flag": "figure_never_ended",
                          "detail": f"figure {base!r} was still open at the "
                                    "end of the job; emitted as an open figure"})

        provenance = {
            "generator": f"survey-linework {__version__}",
            "codeset_name": self.codeset.name,
            "codeset_version": self.codeset.version,
            "job_sha256": self._result.job_meta.get("sha256", ""),
            "figure_index": self._figure_index,
        }
        figure = Figure(
            id=base, base_code=base, prefix=pfx.prefix,
            layer=pfx.layer, style=pfx.style,
            vertices=list(fig.vertices), arc_spans=list(fig.arc_spans),
            closed=closed, close_method=close_method,
            misclosure_m=(round(misclosure, 4) if closed else None),
            flags=flags, provenance=provenance)
        self._result.figures.append(figure)
        self._figure_index += 1
        for fl in flags:
            self._result.flags.append({"figure": base, **fl})
        del self._open[base]

        if fig.offset_m is not None:
            self._emit_offset(figure, fig.offset_m)

    def _emit_offset(self, figure: Figure, offset_m: float) -> None:
        off_id = f"{figure.id}_OFF"
        if any(f.id == off_id for f in self._result.figures):
            raise FigureBuildError(
                f"offset figure id {off_id!r} already exists")
        chorded = figure.chorded_points_3d(self.offset_chord_sagitta_m)
        ring = chorded[:-1] if figure.closed else chorded
        pts2d = [(e, n) for e, n, _ in ring]
        try:
            off2d = offset_polyline(pts2d, offset_m)
        except LineworkError as exc:
            raise FigureBuildError(
                f"figure {figure.id!r}: offset by {offset_m} m failed: "
                f"{exc}") from exc
        elevs = [el for _, _, el in ring]
        # Offset vertices follow the chorded polyline, so they are named
        # after the offset figure, not after field shots.
        vertices = [
            FigureVertex(name=f"{off_id}.{i}", easting=e, northing=n,
                         elevation=el)
            for i, ((e, n), el) in enumerate(zip(off2d, elevs))]
        side = "right" if offset_m >= 0 else "left"
        provenance = dict(figure.provenance)
        provenance["figure_index"] = self._figure_index
        provenance["offset_of"] = figure.id
        provenance["offset_m"] = offset_m
        misclosure = (misclosure_m((vertices[0].easting, vertices[0].northing),
                                    (vertices[-1].easting, vertices[-1].northing))
                      if figure.closed else None)
        off_fig = Figure(
            id=off_id, base_code=off_id, prefix=figure.prefix,
            layer=figure.layer, style="dashed",
            vertices=vertices, arc_spans=[],
            closed=figure.closed,
            close_method="offset" if figure.closed else "none",
            misclosure_m=(round(misclosure, 4)
                          if misclosure is not None else None),
            flags=[{"flag": "offset_figure",
                    "detail": f"parallel offset of {figure.id!r} by "
                              f"{offset_m} m to the {side} of travel; "
                              "computed on the chorded polyline"}],
            offset_of=figure.id, offset_m=offset_m, provenance=provenance)
        self._result.figures.append(off_fig)
        self._figure_index += 1

    # -- unknown codes -----------------------------------------------------------
    def _unknown_code_msg(self, name: str, raw: str, base: str) -> str:
        corpus = list(self.prefixes.known_prefixes())
        for key in self.keys.keys:
            plain = key.pattern.replace("*", "").replace("?", "")
            if plain:
                corpus.append(plain)
        suggestions = difflib.get_close_matches(base, corpus, n=3, cutoff=0.5)
        hint = (f"; did you mean: {', '.join(suggestions)}?"
                if suggestions else
                "; no similar prefix or description key found")
        return (f"unknown code {base!r} on point {name!r} (raw code {raw!r}): "
                f"matches no figure prefix and no description key{hint} "
                "Fix the field code, or add a description key / figure prefix.")


def build_figures(project: Any, codeset: LineworkCodeSet,
                  keys: DescriptionKeys, prefixes: FigurePrefixDB,
                  job_sha256: str = "",
                  offset_chord_sagitta_m: float = 0.01) -> BuildResult:
    """One-shot API: coded project -> BuildResult."""
    return FigureBuilder(codeset, keys, prefixes,
                         offset_chord_sagitta_m).build(project, job_sha256)
