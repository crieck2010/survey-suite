"""Plane geometry for linework figures: arcs, chording, offsets.

All coordinates are (easting, northing) metres in the project CRS.
Angles are radians, azimuth-style (clockwise from north).

Arcs are *chorded* into polylines for drafting because survey-drafting
has no arc entity type: the chord count is chosen so no chord deviates
from the true arc by more than ``max_sagitta_m`` (configurable,
documented).
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from .errors import LineworkError

XY = Tuple[float, float]


def _azimuth(from_xy: XY, to_xy: XY) -> float:
    """Azimuth (rad, clockwise from north) from one point to another."""
    return math.atan2(to_xy[0] - from_xy[0], to_xy[1] - from_xy[1])


def circle_from_3_points(p1: XY, p2: XY, p3: XY) -> Tuple[XY, float]:
    """Centre and radius of the circle through three points.

    Raises LineworkError when the points are collinear (or coincident) --
    no circle exists, and guessing one would be fabrication.
    """
    (x1, y1), (x2, y2), (x3, y3) = p1, p2, p3
    d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        raise LineworkError(
            "three-point arc is degenerate: the begin, mid and end points "
            "are collinear or coincident; no circle fits them")
    s1 = x1 * x1 + y1 * y1
    s2 = x2 * x2 + y2 * y2
    s3 = x3 * x3 + y3 * y3
    cx = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
    cy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    r = math.hypot(x1 - cx, y1 - cy)
    return (cx, cy), r


def _turn_of(center: XY, p1: XY, pmid: XY, p3: XY) -> str:
    """Steering direction ('left' or 'right') for travel p1 -> p3 via pmid.

    'turn' is the traveller's steering: the position vector rotates
    clockwise about the centre on a right turn, counter-clockwise on a
    left turn. Note this is *opposite* the side the arc bulges toward:
    a minor arc bulging left of the chord direction is steered right
    (the centre sits opposite the bulge).
    """
    a1 = _azimuth(center, p1)
    a3 = _azimuth(center, p3)
    cross = (p3[0] - p1[0]) * (pmid[1] - p1[1]) - (p3[1] - p1[1]) * (pmid[0] - p1[0])
    # cross > 0 (EN orientation): pmid lies left of travel p1 -> p3, so the
    # arc bulges left and the traveller steers right.
    if abs(cross) < 1e-12:
        # Degenerate side: fall back to the shorter sweep.
        sweep_right = (a3 - a1) % (2.0 * math.pi)
        return "right" if sweep_right <= math.pi else "left"
    return "right" if cross > 0 else "left"


def radius_arc(p1: XY, pmid: XY, p3: XY, radius: float) -> Tuple[XY, float, str]:
    """Centre, radius and turn of the radius-mode arc p1 -> p3.

    The arc has the given radius and bulges toward the side of the chord
    p1->p3 that ``pmid`` (the side-indicator shot) sits on. Raises
    LineworkError when ``radius`` is smaller than half the chord (no such
    arc exists) or non-positive.
    """
    if radius <= 0:
        raise LineworkError(f"radius-mode arc: radius must be positive, got {radius}")
    chord = math.hypot(p3[0] - p1[0], p3[1] - p1[1])
    if chord == 0.0:
        raise LineworkError("radius-mode arc: begin and end points coincide")
    if radius < chord / 2.0 - 1e-9:
        raise LineworkError(
            f"radius-mode arc: radius {radius} m is smaller than half the "
            f"chord {chord:.3f} m -- no such arc exists")
    mx, my = (p1[0] + p3[0]) / 2.0, (p1[1] + p3[1]) / 2.0
    dx, dy = p3[0] - p1[0], p3[1] - p1[1]
    # Unit perpendicular; two candidate centres at +/- h along it.
    h = math.sqrt(max(radius * radius - (chord / 2.0) ** 2, 0.0))
    px, py = -dy / chord, dx / chord
    cands = [(mx + px * h, my + py * h), (mx - px * h, my - py * h)]
    # The arc bulges toward pmid's side of the chord, so the centre sits
    # on the OPPOSITE side (as with any minor arc).
    cross_mid = dx * (pmid[1] - p1[1]) - dy * (pmid[0] - p1[0])
    if abs(cross_mid) < 1e-12:
        raise LineworkError(
            "radius-mode arc: the side-indicator point sits on the chord; "
            "its side (and therefore the arc) is ambiguous")
    def side(c: XY) -> float:
        return dx * (c[1] - p1[1]) - dy * (c[0] - p1[0])
    center = cands[0] if (side(cands[0]) * cross_mid < 0) else cands[1]
    turn = _turn_of(center, p1, pmid, p3)
    return center, radius, turn


def chord_arc(center: XY, radius: float, a_start: float, a_end: float,
              turn: str, max_sagitta_m: float) -> List[XY]:
    """Chord a circular arc into a polyline within a sagitta tolerance.

    ``a_start``/``a_end`` are azimuths (rad) of the arc endpoints about the
    centre; ``turn`` is the traveller's steering -- "right" rotates the
    position vector clockwise about the centre (azimuth increasing),
    "left" counter-clockwise (azimuth decreasing).
    The chord count is the smallest n with sagitta <= max_sagitta_m:
    sagitta = R(1 - cos(dtheta/2)). Returns n+1 points, endpoints included.
    """
    if max_sagitta_m <= 0:
        raise LineworkError("chord sagitta tolerance must be positive")
    if radius <= 0:
        raise LineworkError("chord_arc: radius must be positive")
    if turn == "right":
        sweep = (a_end - a_start) % (2.0 * math.pi)
        sign = 1.0
    elif turn == "left":
        sweep = (a_start - a_end) % (2.0 * math.pi)
        sign = -1.0
    else:
        raise LineworkError(f"chord_arc: turn must be 'left'/'right', got {turn!r}")
    if sweep < 1e-12:
        return [(center[0] + radius * math.sin(a_start),
                 center[1] + radius * math.cos(a_start))]
    # sagitta <= s  <=>  dtheta <= 2*acos(1 - s/R)
    ratio = max(1.0 - max_sagitta_m / radius, -1.0)
    max_dtheta = 2.0 * math.acos(min(ratio, 1.0))
    n = max(1, math.ceil(sweep / max_dtheta))
    pts = []
    for k in range(n + 1):
        a = a_start + sign * sweep * k / n
        pts.append((center[0] + radius * math.sin(a),
                    center[1] + radius * math.cos(a)))
    return pts


def three_point_arc(p1: XY, pmid: XY, p3: XY) -> Tuple[XY, float, str]:
    """Centre, radius and turn of the arc through three points (p1 -> p3).

    The arc passes through ``pmid``; the turn follows the traveller's
    steering convention (see _turn_of).
    """
    center, radius = circle_from_3_points(p1, pmid, p3)
    return center, radius, _turn_of(center, p1, pmid, p3)


def arc_through_points(p1: XY, pmid: XY, p3: XY,
                       max_sagitta_m: float) -> Tuple[List[XY], XY, float, str]:
    """Chorded three-point arc p1 -> p3 passing through pmid.

    Returns (chorded points, centre, radius, turn).
    """
    center, radius, turn = three_point_arc(p1, pmid, p3)
    a1, a3 = _azimuth(center, p1), _azimuth(center, p3)
    pts = chord_arc(center, radius, a1, a3, turn, max_sagitta_m)
    # Pin the endpoints exactly (chord_arc already does, but be explicit).
    pts[0] = p1
    pts[-1] = p3
    return pts, center, radius, turn


def misclosure_m(p_first: XY, p_last: XY) -> float:
    """2D misclosure distance between first and last vertex, metres."""
    return math.hypot(p_last[0] - p_first[0], p_last[1] - p_first[1])


def offset_polyline(pts: List[XY], distance_m: float) -> List[XY]:
    """Parallel offset of a polyline by a signed distance.

    Positive = right of the direction of travel. Miter joins; endpoints
    use their single-segment normal.

    Limitations (documented, v0.1): sharp inside corners can spike the
    miter; self-intersecting offsets are not detected or repaired; arcs
    must be chorded before offsetting (the figure builder does this).
    """
    if len(pts) < 2:
        raise LineworkError("offset needs at least 2 points")
    n = len(pts)

    def seg(i: int) -> Tuple[float, float]:
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        L = math.hypot(dx, dy)
        if L == 0.0:
            raise LineworkError("offset: coincident consecutive vertices")
        return dx / L, dy / L

    def right_normal(d: Tuple[float, float]) -> Tuple[float, float]:
        # Rotate direction clockwise 90 deg: right of travel in EN coords.
        return (d[1], -d[0])

    dirs = [seg(i) for i in range(n - 1)]
    normals = [right_normal(d) for d in dirs]
    out: List[XY] = []
    for i in range(n):
        if i == 0:
            m = normals[0]
            denom = 1.0
        elif i == n - 1:
            m = normals[-1]
            denom = 1.0
        else:
            nx = normals[i - 1][0] + normals[i][0]
            ny = normals[i - 1][1] + normals[i][1]
            L = math.hypot(nx, ny)
            if L < 1e-9:  # 180-degree reversal: fall back to outgoing normal
                m = normals[i]
                denom = 1.0
            else:
                m = (nx / L, ny / L)
                denom = m[0] * normals[i][0] + m[1] * normals[i][1]
                if abs(denom) < 0.2:  # near-spike: clamp the miter
                    m = normals[i]
                    denom = 1.0
        scale = distance_m / denom
        out.append((pts[i][0] + m[0] * scale, pts[i][1] + m[1] * scale))
    return out
