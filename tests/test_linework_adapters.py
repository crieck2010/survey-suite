"""Adapters: figures -> survey-drafting entities / survey-cogo points."""
from __future__ import annotations

import pytest

from conftest import P, StubProject, StubSession
from linework.adapters import figures_to_cogo, figures_to_drafting_layers
from linework.errors import LineworkError
from linework.interchange import dump_figures


@pytest.fixture()
def envelope(builder):
    project = StubProject(sessions=[StubSession(points=[
        # Open straight figure.
        P("101", "EC1 *bl", 100.0, 200.0),
        P("102", "EC1 *el", 120.0, 200.0),
        # Closed building (explicit close).
        P("201", "BLDG1 *bl", 0.0, 0.0),
        P("202", "BLDG1", 10.0, 0.0),
        P("203", "BLDG1", 10.0, 10.0),
        P("204", "BLDG1", 0.0, 10.0),
        P("205", "BLDG1 *cl", 0.0, 0.0),
        # Curved figure: arcs must be chorded (no arc entity type).
        P("301", "EP1 *bl", 0.0, 0.0),
        P("302", "EP1 *bc3", 0.0, 0.0),
        P("303", "EP1", 5.0, 1.0),
        P("304", "EP1 *ec3", 10.0, 0.0),
        P("305", "EP1 *el", 20.0, 0.0),
    ])])
    return dump_figures(builder.build(project))


def test_open_figure_becomes_line_entity(envelope):
    layers = figures_to_drafting_layers(envelope)
    line = layers["linework"][0]
    assert line["type"] == "line"
    # Drafting (x, y) = (easting, northing), in order.
    assert line["pts"] == [(100.0, 200.0), (120.0, 200.0)]


def test_closed_figure_becomes_polygon_entity(envelope):
    layers = figures_to_drafting_layers(envelope)
    polys = [e for e in layers["linework"] if e["type"] == "polygon"]
    assert len(polys) == 1
    assert polys[0]["hatch"] is False
    assert polys[0]["pts"][0] == polys[0]["pts"][-1] == (0.0, 0.0)
    assert len(polys[0]["pts"]) == 6  # 5 vertices + closure


def test_arcs_are_chorded_no_arc_entity_type(envelope):
    layers = figures_to_drafting_layers(envelope, chord_sagitta_m=0.01)
    ents = layers["linework"]
    # survey-drafting has no arc entity type: only line/polygon/point.
    assert all(e["type"] in ("line", "polygon", "point") for e in ents)
    assert not any(e["type"] == "arc" for e in ents)
    curved = [e for e in ents if e["type"] == "line"
              and e["pts"][0] == (0.0, 0.0) and e["pts"][-1] == (20.0, 0.0)]
    assert len(curved) == 1
    assert len(curved[0]["pts"]) > 4  # arc became many chords


def test_points_layer_entities(envelope):
    layers = figures_to_drafting_layers(envelope)
    # Every coded point in this fixture keys to the "linework" layer
    # (EC*/EP*/BLDG*); point entities land on their resolved layer.
    pts = layers["linework"]
    point_ents = [p for p in pts if p["type"] == "point"]
    assert len(point_ents) == 12
    assert point_ents[0]["at"] == (100.0, 200.0)
    assert point_ents[0]["label"] == "101"


def test_figures_land_on_prefix_target_layer(envelope):
    layers = figures_to_drafting_layers(envelope)
    # BLDG prefix targets "linework" in the template; the easement prefix
    # targets "easements" -- check the mechanism via a custom envelope.
    assert "linework" in layers


def test_cogo_adapter_needs_cogo_installed(envelope):
    cogo = pytest.importorskip("cogo")
    out = figures_to_cogo(envelope)
    assert set(out) == {"EC1", "BLDG1", "EP1"}
    pts = out["EC1"]
    assert pts[0].northing == pytest.approx(200.0)
    assert pts[0].easting == pytest.approx(100.0)
    # Closed figure: area via the real cogo engine.
    area = cogo.polygon_area(out["BLDG1"])
    assert area == pytest.approx(100.0)
    perim = cogo.polygon_perimeter(out["BLDG1"])
    assert perim == pytest.approx(40.0)


def test_cogo_adapter_missing_cogo(monkeypatch, envelope):
    import sys
    # None in sys.modules makes "from cogo import Point" raise ImportError.
    monkeypatch.setitem(sys.modules, "cogo", None)
    with pytest.raises(LineworkError, match="survey-cogo"):
        figures_to_cogo(envelope)


def test_bad_sagitta_rejected(envelope):
    with pytest.raises(LineworkError, match="sagitta"):
        figures_to_drafting_layers(envelope, chord_sagitta_m=0)
