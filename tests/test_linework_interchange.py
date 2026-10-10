"""Interchange: round-trip fidelity and loud schema rejection."""
from __future__ import annotations

import pytest

from conftest import P, StubProject, StubSession
from linework.errors import InterchangeError
from linework.figures import build_figures
from linework.interchange import (
    dump_figures,
    figures_from_dict,
    load_figures,
    read_figures,
    write_figures,
)


@pytest.fixture()
def envelope(builder):
    project = StubProject(sessions=[StubSession(points=[
        P("101", "EC1 *bl", 100.0, 200.0, 5.0),
        P("102", "EC1 *el", 110.0, 200.0, 5.0),
        P("103", "EP1 *bc3", 0.0, 0.0),
        P("104", "EP1", 5.0, 1.0),
        P("105", "EP1 *ec3", 10.0, 0.0),
        P("106", "EP1 *el", 20.0, 0.0),
        P("107", "", 1.0, 1.0),
    ])])
    return dump_figures(builder.build(project, job_sha256="deadbeef"))


def test_envelope_shape(envelope):
    assert envelope["format"] == "survey-linework/figures"
    assert envelope["schema_version"] == 1
    assert envelope["generator"].startswith("survey-linework ")
    assert envelope["job"]["sha256"] == "deadbeef"
    assert envelope["codeset"] == {"name": "emlid", "version": "1.0"}
    assert len(envelope["figures"]) == 2
    assert len(envelope["points"]) == 7
    counts = envelope["report"]["counts"]
    assert counts["n_figures"] == 2
    assert counts["n_coded_points"] == 6
    assert counts["n_uncoded_points"] == 1


def test_figure_dict_carries_provenance_and_segments(envelope):
    fig = next(f for f in envelope["figures"] if f["id"] == "EP1")
    assert fig["provenance"]["codeset_name"] == "emlid"
    assert fig["provenance"]["job_sha256"] == "deadbeef"
    assert fig["source_points"] == ["103", "104", "105", "106"]
    arc = next(s for s in fig["segments"] if s["kind"] == "arc")
    assert arc["radius"] == pytest.approx(13.0)
    assert set(arc) >= {"kind", "from", "to", "mode", "center", "radius", "turn"}


def test_write_read_round_trip(tmp_path, envelope):
    path = str(tmp_path / "figs.json")
    import json
    with open(path, "w") as fh:
        json.dump(envelope, fh)
    data = read_figures(path)
    assert data["figures"] == envelope["figures"]
    figs = figures_from_dict(data)
    assert [f.id for f in figs] == ["EC1", "EP1"]


def test_write_figures_helper(tmp_path, builder):
    project = StubProject(sessions=[StubSession(
        points=[P("101", "EC1 *bl", 0.0, 0.0),
                P("102", "EC1 *el", 1.0, 0.0)])])
    result = builder.build(project)
    path = str(tmp_path / "out.json")
    write_figures(result, path)
    assert read_figures(path)["format"] == "survey-linework/figures"


def test_rejects_newer_schema_loudly(envelope):
    envelope["schema_version"] = 99
    with pytest.raises(InterchangeError, match="newer than this reader"):
        load_figures(envelope)


def test_rejects_wrong_format(envelope):
    envelope["format"] = "survey-field/job"
    with pytest.raises(InterchangeError, match="not a survey-linework"):
        load_figures(envelope)


def test_rejects_missing_keys(envelope):
    del envelope["report"]
    with pytest.raises(InterchangeError, match="missing required key"):
        load_figures(envelope)


def test_read_missing_file():
    with pytest.raises(InterchangeError, match="cannot read"):
        read_figures("/nonexistent/figs.json")
