"""Tests for the Figures toolbox orchestration (suite.runners figures API).

Tk-free: build, QA surfacing, strict gate, manifest round-trip, stats,
canvas data. GUI construction tests live in test_app_smoke.py.
"""
import json
import os

import pytest

from suite import project as project_mod
from suite import runners
from suite.project import SurveyProject


def _coded_job(path, rows):
    """Write a synthetic .sfield.json job from (name, code, e, n) rows."""
    from field import jobfile, models
    pts = [models.SurveyPoint(name=n, code=c, easting=e, northing=nn,
                              elevation=100.0, solution="FIX")
           for n, c, e, nn in rows]
    sess = models.RoverSession(id="s1", base_station_id="BASE-1",
                               date="2026-10-10", points=pts)
    proj = models.Project(name="t", crs="test", sessions=[sess])
    jobfile.write_job(proj, path)
    return path


@pytest.fixture()
def job_path(tmp_path):
    rows = [
        # closed square via explicit *cl
        ("101", "EC1 *bl", 500000.0, 4500000.0),
        ("102", "EC1", 500060.0, 4500000.0),
        ("103", "EC1", 500060.0, 4500060.0),
        ("104", "EC1", 500000.0, 4500060.0),
        ("105", "EC1 *cl", 500000.0, 4500000.0),
        # open figure, properly ended
        ("106", "EP1 *bl", 500100.0, 4500000.0),
        ("107", "EP1 *el", 500160.0, 4500000.0),
        # never ended -> figure_never_ended QA flag
        ("108", "BLDG1 *bl", 500200.0, 4500000.0),
        ("109", "BLDG1", 500260.0, 4500010.0),
    ]
    return _coded_job(str(tmp_path / "job.sfield.json"), rows)


@pytest.fixture()
def figures_path(tmp_path, job_path):
    out = str(tmp_path / "t.figures.json")
    res = runners.run_figures_build(job_path, "preset:emlid", out)
    assert res.ok
    return out


def test_run_figures_build_counts(job_path, tmp_path):
    out = str(tmp_path / "b.figures.json")
    res = runners.run_figures_build(job_path, "preset:emlid", out)
    assert res.ok
    assert res.counts["n_figures"] == 3
    assert res.counts["n_closed_figures"] == 1
    assert res.counts["n_flags"] == 2
    assert res.codeset_name == "emlid"
    assert os.path.isfile(out)
    data = runners.read_figures(out)
    assert data["format"] == "survey-linework/figures"


def test_run_figures_build_bad_codeset_fails_loud(job_path, tmp_path):
    with pytest.raises(ValueError, match="code set invalid|unknown code-set"):
        runners.run_figures_build(job_path, "preset:nope",
                                  str(tmp_path / "x.json"))


def test_resolve_codeset_presets():
    emlid = runners.resolve_codeset("preset:emlid")
    civil = runners.resolve_codeset("preset:civil3d")
    assert emlid.name == "emlid"
    assert civil.name == "civil3d"
    with pytest.raises(ValueError, match="unknown code-set preset"):
        runners.resolve_codeset("preset:bogus")


def test_qa_flags_have_plain_language(figures_path):
    data = runners.read_figures(figures_path)
    flags = runners.qa_flag_list(data)
    by_code = {f["flag"]: f for f in flags}
    assert "figure_never_ended" in by_code
    fl = by_code["figure_never_ended"]
    assert fl["figure"] == "BLDG1"
    assert fl["explanation"]  # plain-language, not the raw code
    assert "open" in fl["explanation"].lower()


def test_strict_gate_refuses_and_relaxes(figures_path):
    problems = runners.figures_strict_problems(figures_path and
                                               runners.read_figures(
                                                   figures_path))
    assert problems, "expected QA flags on the fixture"
    assert any("BLDG1" in p for p in problems)
    with pytest.raises(runners.FiguresRefused, match="strict mode"):
        runners.figures_extra_layers(figures_path, strict=True)
    # relaxed: entities flow
    layers = runners.figures_extra_layers(figures_path, strict=False)
    assert "linework" in layers
    assert any(e["type"] == "polygon" for e in layers["linework"])


def test_strict_gate_clean_figures_pass(tmp_path, job_path):
    rows = [
        ("101", "EC1 *bl", 500000.0, 4500000.0),
        ("102", "EC1", 500060.0, 4500000.0),
        ("103", "EC1 *el", 500060.0, 4500060.0),
    ]
    job = _coded_job(str(tmp_path / "clean.sfield.json"), rows)
    out = str(tmp_path / "clean.figures.json")
    runners.run_figures_build(job, "preset:emlid", out)
    data = runners.read_figures(out)
    assert runners.figures_strict_problems(data) == []
    layers = runners.figures_extra_layers(out, strict=True)
    assert "linework" in layers


def test_figure_stats_closed_area(figures_path):
    data = runners.read_figures(figures_path)
    st = runners.figure_stats(data, "EC1")
    assert st["closed"] is True
    assert st["n_vertices"] == 5
    # 60 m x 60 m square
    assert st["area_m2"] == pytest.approx(3600.0, rel=1e-6)
    assert st["length_m"] == pytest.approx(240.0, rel=1e-6)
    assert st["provenance"]["codeset_name"] == "emlid"


def test_figure_stats_unknown_figure(figures_path):
    data = runners.read_figures(figures_path)
    with pytest.raises(ValueError, match="unknown figure"):
        runners.figure_stats(data, "NOPE")


def test_figure_records_for_tree(figures_path):
    data = runners.read_figures(figures_path)
    recs = {r["id"]: r for r in runners.figure_records(data)}
    assert set(recs) == {"EC1", "EP1", "BLDG1"}
    assert recs["EC1"]["closed"] is True
    assert recs["BLDG1"]["n_flags"] == 2
    assert recs["EP1"]["n_flags"] == 0


def test_figures_canvas_data(figures_path):
    data = runners.read_figures(figures_path)
    canvas = runners.figures_canvas_data(data)
    assert len(canvas) == 3
    for fig in canvas:
        assert len(fig["pts"]) >= 2
        assert all(len(p) == 2 for p in fig["pts"])


def test_manifest_round_trip_new_fields(tmp_path):
    proj = SurveyProject.new("t", str(tmp_path / "proj"))
    proj.set_artifact("figures_path", str(tmp_path / "proj" / "t.figures.json"))
    proj.codeset_source = "preset:civil3d"
    proj.figures_strict = False
    proj.figures_in_draft = True
    sproj = proj.save()
    loaded = SurveyProject.load(sproj)
    assert loaded.figures_path == "t.figures.json"  # stored relative
    assert loaded.codeset_source == "preset:civil3d"
    assert loaded.figures_strict is False
    assert loaded.figures_in_draft is True


def test_manifest_old_file_loads_with_defaults(tmp_path):
    # a pre-v0.4.0 manifest without the figures fields still loads
    d = {"format": "survey-suite/project", "schema_version": 1,
         "name": "old", "crs": "", "created_utc": "", "modified_utc": ""}
    p = tmp_path / "old.sproj"
    p.write_text(json.dumps(d))
    loaded = SurveyProject.load(str(p))
    assert loaded.figures_path is None
    assert loaded.codeset_source == "preset:emlid"
    assert loaded.figures_strict is True
    assert loaded.figures_in_draft is False


def test_toolbox_helpers_tk_free(figures_path):
    from suite.toolbox_figures import figure_extent, summarize_figures
    data = runners.read_figures(figures_path)
    summ = summarize_figures(data)
    assert summ["n_figures"] == 3
    assert summ["n_closed"] == 1
    assert summ["n_flagged"] == 1
    assert summ["codeset"] == "emlid"
    canvas = runners.figures_canvas_data(data)
    ext = figure_extent(canvas, "EC1")
    assert ext == (500000.0, 4500000.0, 500060.0, 4500060.0)
    assert figure_extent(canvas, "NOPE") is None
