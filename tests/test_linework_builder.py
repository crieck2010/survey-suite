"""Figure builder: coded sequences -> figures, and every fail-loud path."""
from __future__ import annotations

import pytest

from conftest import P, StubProject, StubSession
from linework.errors import FigureBuildError
from linework.figures import build_figures


def build(points, builder, sha="abc123"):
    project = StubProject(sessions=[StubSession(points=points)])
    return builder.build(project, job_sha256=sha)


def test_straight_figure_begin_continue_end(builder):
    pts = [P("101", "EC1 *bl", 100.0, 200.0),
           P("102", "EC1 *c", 110.0, 200.0),
           P("103", "EC1 *el", 120.0, 200.0)]
    res = build(pts, builder)
    assert len(res.figures) == 1
    fig = res.figures[0]
    assert fig.id == "EC1"
    assert [v.name for v in fig.vertices] == ["101", "102", "103"]
    assert fig.closed is False
    assert all(s["kind"] == "line" for s in fig.segments())
    assert fig.provenance["codeset_name"] == "emlid"
    assert fig.provenance["job_sha256"] == "abc123"
    assert fig.provenance["figure_index"] == 0


def test_auto_begin_plain_codes(builder):
    pts = [P("101", "EC1", 100.0, 200.0),
           P("102", "EC1", 110.0, 200.0)]
    res = build(pts, builder)
    assert len(res.figures) == 1
    assert res.figures[0].id == "EC1"
    assert res.flags[0]["flag"] == "figure_never_ended"


def test_end_without_begin_fails_loud(builder):
    with pytest.raises(FigureBuildError, match="end-without-begin"):
        build([P("101", "EC1 *el", 100.0, 200.0)], builder)


def test_continue_without_begin_fails_loud(builder):
    with pytest.raises(FigureBuildError, match="continue-without-begin"):
        build([P("101", "EC1 *c", 100.0, 200.0)], builder)


def test_close_without_begin_fails_loud(builder):
    with pytest.raises(FigureBuildError, match="close-without-begin"):
        build([P("101", "EC1 *cl", 100.0, 200.0)], builder)


def test_begin_twice_fails_loud(builder):
    pts = [P("101", "EC1 *bl", 100.0, 200.0),
           P("102", "EC1 *bl", 110.0, 200.0)]
    with pytest.raises(FigureBuildError, match="already open"):
        build(pts, builder)


def test_unknown_code_fails_loud_with_suggestion(builder):
    with pytest.raises(FigureBuildError, match=r"did you mean:.*EC"):
        build([P("101", "ECX", 100.0, 200.0)], builder)


def test_unknown_code_names_point_and_raw(builder):
    try:
        build([P("101", "QQQ", 100.0, 200.0)], builder)
    except FigureBuildError as exc:
        assert "'101'" in str(exc) and "'QQQ'" in str(exc)
    else:
        raise AssertionError("expected FigureBuildError")


def test_empty_code_gets_default_key_and_no_figure(builder):
    res = build([P("101", "", 100.0, 200.0)], builder)
    assert res.figures == []
    rec = res.points[0]
    assert rec.uncoded is True
    assert rec.figure is None
    assert rec.layer == "points"  # the default key
    assert res.counts()["n_uncoded_points"] == 1


def test_coded_point_without_coordinates_fails_loud(builder):
    pt = P("101", "EC1 *bl", None, None)
    with pytest.raises(FigureBuildError, match="no easting/northing"):
        build([pt], builder)


def test_explicit_close_reports_misclosure(builder):
    pts = [P("101", "BLDG1 *bl", 0.0, 0.0),
           P("102", "BLDG1", 10.0, 0.0),
           P("103", "BLDG1", 10.0, 10.0),
           P("104", "BLDG1", 0.0, 10.0),
           P("105", "BLDG1 *cl", 0.02, 0.01)]
    res = build(pts, builder)
    fig = res.figures[0]
    assert fig.closed is True
    assert fig.close_method == "explicit"
    assert fig.misclosure_m == pytest.approx(0.0224, abs=1e-3)
    assert fig.layer == "linework"


def test_auto_close_snaps_within_tolerance(builder):
    pts = [P("101", "BLDG1 *bl", 0.0, 0.0),
           P("102", "BLDG1", 10.0, 0.0),
           P("103", "BLDG1 *el", 0.03, 0.04)]  # 5 cm from start, tol 0.10
    res = build(pts, builder)
    fig = res.figures[0]
    assert fig.closed is True
    assert fig.close_method == "auto"
    assert fig.misclosure_m == pytest.approx(0.05)


def test_unclosed_expected_closed_is_flagged(builder):
    pts = [P("101", "BLDG1 *bl", 0.0, 0.0),
           P("102", "BLDG1", 10.0, 0.0),
           P("103", "BLDG1 *el", 10.0, 10.0)]  # far from start: no auto snap
    res = build(pts, builder)
    fig = res.figures[0]
    assert fig.closed is True  # auto_close still snaps...
    assert fig.close_method == "auto"
    assert any(f["flag"] == "closure_exceeds_tolerance"
               for f in res.flags)


def test_expected_closed_ended_open_flagged_without_auto_close(
        builder, codeset, keys, prefixes):
    # Rebuild the DB with BLDG auto_close off: an ended-but-open building
    # is flagged, not snapped.
    from dataclasses import replace

    from linework.figures import FigureBuilder
    from linework.prefixes import FigurePrefixDB
    new_prefixes = [replace(p, auto_close=False) if p.prefix == "BLDG" else p
                    for p in prefixes.prefixes]
    db = FigurePrefixDB(prefixes=new_prefixes).validate()
    b = FigureBuilder(codeset, keys, db)
    pts = [P("101", "BLDG1 *bl", 0.0, 0.0),
           P("102", "BLDG1 *el", 10.0, 0.0)]
    res = build(pts, b)
    fig = res.figures[0]
    assert fig.closed is False
    assert any(f["flag"] == "unclosed_expected_closed" for f in res.flags)


def test_three_point_arc(builder):
    pts = [P("101", "EP1 *bl", 0.0, 0.0),
           P("102", "EP1 *bc3", 0.0, 0.0),   # curve begin at (0,0)
           P("103", "EP1", 5.0, 1.0),        # mid shot
           P("104", "EP1 *ec3", 10.0, 0.0),  # curve end
           P("105", "EP1 *el", 20.0, 0.0)]
    res = build(pts, builder)
    fig = res.figures[0]
    assert len(fig.arc_spans) == 1
    span = fig.arc_spans[0]
    assert span.mode == "3pt"
    assert (span.start_idx, span.end_idx) == (1, 3)
    assert span.radius == pytest.approx(13.0)
    assert span.turn == "right"
    kinds = [s["kind"] for s in fig.segments()]
    assert kinds == ["line", "arc", "line"]


def test_radius_arc(builder):
    pts = [P("101", "EP1 *bl", 0.0, 0.0),
           P("102", "EP1 *bcr R=13", 0.0, 0.0),
           P("103", "EP1", 5.0, 1.0),
           P("104", "EP1 *ecr", 10.0, 0.0),
           P("105", "EP1 *el", 20.0, 0.0)]
    res = build(pts, builder)
    span = res.figures[0].arc_spans[0]
    assert span.mode == "radius"
    assert span.radius == pytest.approx(13.0)
    assert span.turn == "right"


def test_radius_arc_too_small_fails_loud(builder):
    pts = [P("101", "EP1 *bcr R=4", 0.0, 0.0),
           P("102", "EP1", 5.0, 1.0),
           P("103", "EP1 *ecr", 10.0, 0.0)]
    with pytest.raises(FigureBuildError, match="smaller than half the chord"):
        build(pts, builder)


def test_curve_without_mid_point_fails_loud(builder):
    pts = [P("101", "EP1 *bc3", 0.0, 0.0),
           P("102", "EP1 *ec3", 10.0, 0.0)]
    with pytest.raises(FigureBuildError, match="no intermediate point"):
        build(pts, builder)


def test_curve_with_two_mids_fails_loud(builder):
    pts = [P("101", "EP1 *bc3", 0.0, 0.0),
           P("102", "EP1", 5.0, 1.0),
           P("103", "EP1", 7.0, 0.5),
           P("104", "EP1 *ec3", 10.0, 0.0)]
    with pytest.raises(FigureBuildError, match="split the curve"):
        build(pts, builder)


def test_end_curve_without_begin_curve_fails_loud(builder):
    pts = [P("101", "EP1 *bl", 0.0, 0.0),
           P("102", "EP1 *ec3", 10.0, 0.0)]
    with pytest.raises(FigureBuildError, match="no open curve"):
        build(pts, builder)


def test_unended_curve_at_end_fails_loud(builder):
    pts = [P("101", "EP1 *bl", 0.0, 0.0),
           P("102", "EP1 *bc3", 0.0, 0.0),
           P("103", "EP1 *el", 10.0, 0.0)]
    with pytest.raises(FigureBuildError, match="never ended"):
        build(pts, builder)


def test_offset_figure_is_emitted(builder):
    pts = [P("101", "CL1 *bl", 0.0, 0.0),
           P("102", "CL1 *off:+2.0", 10.0, 0.0),
           P("103", "CL1 *el", 20.0, 0.0)]
    res = build(pts, builder)
    assert len(res.figures) == 2
    base, off = res.figures
    assert base.id == "CL1"
    assert off.id == "CL1_OFF"
    assert off.offset_of == "CL1"
    assert off.offset_m == pytest.approx(2.0)
    # +2 right of eastward travel = 2 m south.
    assert [round(v.northing, 6) for v in off.vertices] == [-2.0, -2.0, -2.0]
    assert [round(v.easting, 6) for v in off.vertices] == [0.0, 10.0, 20.0]
    assert off.provenance["figure_index"] == 1


def test_offset_without_distance_fails_loud(builder):
    pts = [P("101", "CL1 *bl", 0.0, 0.0),
           P("102", "CL1 *off", 10.0, 0.0)]
    with pytest.raises(FigureBuildError, match="needs a distance"):
        build(pts, builder)


def test_double_offset_fails_loud(builder):
    pts = [P("101", "CL1 *bl *off:+1.0", 0.0, 0.0),
           P("102", "CL1 *off:+2.0", 10.0, 0.0),
           P("103", "CL1 *el", 20.0, 0.0)]
    with pytest.raises(FigureBuildError, match="already has an offset"):
        build(pts, builder)


def test_offset_without_begin_fails_loud(builder):
    with pytest.raises(FigureBuildError, match="offset-without-begin"):
        build([P("101", "CL1 *off:+1.0", 0.0, 0.0)], builder)


def test_degenerate_single_vertex_figure_fails_loud(builder):
    # Begin and end on the same shot: one vertex can never be a figure.
    with pytest.raises(FigureBuildError, match="at least 2 points"):
        build([P("101", "EC1 *bl *el", 0.0, 0.0)], builder)


def test_figure_index_increments_across_figures(builder):
    pts = [P("101", "EC1 *bl", 0.0, 0.0), P("102", "EC1 *el", 1.0, 0.0),
           P("201", "EC2 *bl", 5.0, 5.0), P("202", "EC2 *el", 6.0, 5.0)]
    res = build(pts, builder)
    assert [f.provenance["figure_index"] for f in res.figures] == [0, 1]
    assert [f.id for f in res.figures] == ["EC1", "EC2"]


def test_vertices_follow_collection_order(builder):
    pts = [P("103", "EC1 *bl", 30.0, 0.0),
           P("101", "EC1", 10.0, 0.0),
           P("102", "EC1 *el", 20.0, 0.0)]
    res = build(pts, builder)
    assert [v.name for v in res.figures[0].vertices] == ["103", "101", "102"]


def test_point_records_carry_description_keys(builder):
    pts = [P("101", "EC1 *bl", 100.0, 200.0, 5.0),
           P("102", "EC1 *el", 110.0, 200.0, 5.1)]
    res = build(pts, builder)
    rec = res.points[0]
    assert rec.base_code == "EC1"
    assert rec.layer == "linework"
    assert rec.figure == "EC1"
    assert rec.uncoded is False


def test_build_figures_one_shot_api(codeset, keys, prefixes):
    project = StubProject(sessions=[StubSession(points=[
        P("101", "EC1 *bl", 0.0, 0.0), P("102", "EC1 *el", 1.0, 0.0)])])
    res = build_figures(project, codeset, keys, prefixes, job_sha256="zz")
    assert len(res.figures) == 1
    assert res.job_meta["sha256"] == "zz"
