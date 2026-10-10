"""Geometry: arcs, chording, offsets, misclosure."""
from __future__ import annotations

import math

import pytest

from linework.errors import LineworkError
from linework.geometry import (
    arc_through_points,
    chord_arc,
    circle_from_3_points,
    misclosure_m,
    offset_polyline,
    radius_arc,
    three_point_arc,
)


def test_circle_from_3_points():
    center, radius = circle_from_3_points((0.0, 0.0), (5.0, 1.0), (10.0, 0.0))
    assert center == pytest.approx((5.0, -12.0))
    assert radius == pytest.approx(13.0)


def test_collinear_points_fail_loud():
    with pytest.raises(LineworkError, match="collinear or coincident"):
        circle_from_3_points((0.0, 0.0), (5.0, 0.0), (10.0, 0.0))


def test_three_point_arc_turn_convention():
    # Mid point north of an eastward chord: the arc bulges left, the
    # traveller steers right (centre sits opposite the bulge).
    center, radius, turn = three_point_arc((0.0, 0.0), (5.0, 1.0), (10.0, 0.0))
    assert turn == "right"
    assert radius == pytest.approx(13.0)


def test_three_point_arc_turn_left():
    # Mid point south of an eastward chord: bulge right, steer left.
    _, _, turn = three_point_arc((0.0, 0.0), (5.0, -1.0), (10.0, 0.0))
    assert turn == "left"


def test_radius_arc_picks_mid_side():
    center, radius, turn = radius_arc((0.0, 0.0), (5.0, 1.0), (10.0, 0.0), 13.0)
    assert center == pytest.approx((5.0, -12.0))
    assert radius == pytest.approx(13.0)
    assert turn == "right"


def test_radius_arc_too_small_fails_loud():
    with pytest.raises(LineworkError, match="smaller than half the chord"):
        radius_arc((0.0, 0.0), (5.0, 1.0), (10.0, 0.0), 4.0)


def test_radius_arc_side_indicator_on_chord_fails():
    with pytest.raises(LineworkError, match="ambiguous"):
        radius_arc((0.0, 0.0), (5.0, 0.0), (10.0, 0.0), 13.0)


def test_chord_arc_respects_sagitta():
    center, radius = (0.0, 0.0), 100.0
    pts = chord_arc(center, radius, 0.0, math.pi / 2, "right",
                    max_sagitta_m=0.01)
    # Every chord midpoint must sit within the sagitta of the true arc.
    worst = 0.0
    for a, b in zip(pts, pts[1:]):
        mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        apothem = math.hypot(mx - center[0], my - center[1])
        worst = max(worst, radius - apothem)
    assert worst <= 0.010001
    # And the chord count is minimal-ish: sagitta formula predicts 56 chords.
    assert len(pts) - 1 == 56


def test_chord_arc_endpoints_exact():
    center, radius = (5.0, -12.0), 13.0
    a1 = math.atan2(0.0 - 5.0, 0.0 - (-12.0))
    a3 = math.atan2(10.0 - 5.0, 0.0 - (-12.0))
    pts = chord_arc(center, radius, a1, a3, "right", 0.001)
    assert pts[0] == pytest.approx((0.0, 0.0))
    assert pts[-1] == pytest.approx((10.0, 0.0))


def test_arc_through_points_passes_through_mid():
    pts, center, radius, turn = arc_through_points(
        (0.0, 0.0), (5.0, 1.0), (10.0, 0.0), 0.001)
    assert pts[0] == (0.0, 0.0)
    assert pts[-1] == (10.0, 0.0)
    # The chorded polyline must come within the sagitta of the mid shot.
    assert min(math.hypot(x - 5.0, y - 1.0) for x, y in pts) <= 0.01


def test_offset_straight_line_right_of_travel():
    out = offset_polyline([(0.0, 0.0), (10.0, 0.0)], 2.0)
    assert out[0] == pytest.approx((0.0, -2.0))
    assert out[1] == pytest.approx((10.0, -2.0))


def test_offset_left_is_negative():
    out = offset_polyline([(0.0, 0.0), (10.0, 0.0)], -2.0)
    assert out[0] == pytest.approx((0.0, 2.0))


def test_offset_preserves_length_on_straight():
    out = offset_polyline([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)], 1.5)
    assert len(out) == 3
    for (x, y) in out:
        assert y == pytest.approx(-1.5)


def test_misclosure():
    assert misclosure_m((0.0, 0.0), (3.0, 4.0)) == pytest.approx(5.0)
