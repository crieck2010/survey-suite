"""Tests for the toolbox registry (suite.toolboxes) -- Tk-free.

Covers build #6: the Toolbox spec, register_toolbox(), the six built-in
toolboxes, auto-discovery of the Coordinates toolbox, the missing-engine
notice wiring, and the Coordinates picker's Tk-free search helpers.
GUI construction tests live in test_app_smoke.py.
"""
import pytest

from suite import toolboxes
from suite.toolboxes import (Toolbox, all_toolboxes, missing_engine_deps,
                             register_toolbox, toolbox_by_id)


def test_seven_toolboxes_registered_in_notebook_order():
    tbs = all_toolboxes()
    assert [t.id for t in tbs] == ["project", "import", "adjust", "map",
                                  "draft", "basemap", "coordinates"]
    assert [t.title for t in tbs] == ["Project", "Import", "Adjust", "Map",
                                     "Draft", "Basemap", "Coordinates"]


def test_toolbox_spec_fields():
    for tb in all_toolboxes():
        assert tb.id and isinstance(tb.id, str)
        assert tb.title and isinstance(tb.title, str)
        assert callable(tb.tab_factory)
        assert isinstance(tb.engine_deps, tuple)
        assert tb.description, tb.id


def test_engine_deps_declared():
    by_id = {t.id: t for t in all_toolboxes()}
    assert by_id["project"].engine_deps == ()
    assert by_id["import"].engine_deps == ("field",)
    assert by_id["adjust"].engine_deps == ("adjustflow",)
    assert "drafting" in by_id["map"].engine_deps
    assert by_id["draft"].engine_deps == ("drafting",)
    assert by_id["basemap"].engine_deps == ("basemap",)
    assert by_id["coordinates"].engine_deps == ("crs",)


def test_toolbox_by_id():
    assert toolbox_by_id("coordinates").title == "Coordinates"
    assert toolbox_by_id("no-such-toolbox") is None


def test_duplicate_id_rejected():
    with pytest.raises(ValueError, match="duplicate toolbox id"):
        register_toolbox(Toolbox(id="project", title="Dupe",
                                 tab_factory=lambda a, n, t: None))


def test_empty_id_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        register_toolbox(Toolbox(id="", title="No id",
                                 tab_factory=lambda a, n, t: None))


def test_missing_engine_deps_detects_absent_engine():
    tb = Toolbox(id="x", title="X", tab_factory=lambda a, n, t: None,
                 engine_deps=["_no_such_engine_xyz"])
    assert missing_engine_deps(tb) == ["_no_such_engine_xyz"]


def test_missing_engine_deps_empty_when_present():
    tb = Toolbox(id="y", title="Y", tab_factory=lambda a, n, t: None,
                 engine_deps=["sys"])
    assert missing_engine_deps(tb) == []


def test_guarded_factory_degrades_to_notice_frame(monkeypatch):
    """A toolbox whose engine is missing builds the notice frame instead
    of calling the real factory (Tk-free: the notice builder is stubbed)."""
    calls = {}

    def fake_notice(notebook, toolbox, missing):
        calls["missing"] = missing
        return "NOTICE"

    monkeypatch.setattr(toolboxes, "_missing_deps_frame", fake_notice)
    tb = register_toolbox(Toolbox(id="_probe", title="Probe",
                                  tab_factory=lambda a, n, t: "REAL",
                                  engine_deps=["_no_such_engine_xyz"]))
    try:
        assert tb.tab_factory(object(), object(), tb) == "NOTICE"
        assert calls["missing"] == ["_no_such_engine_xyz"]
    finally:
        toolboxes.TOOLBOXES.remove(tb)


def test_guarded_factory_calls_through_when_deps_present():
    tb = register_toolbox(Toolbox(id="_probe2", title="Probe2",
                                  tab_factory=lambda a, n, t: "REAL",
                                  engine_deps=["sys"]))
    try:
        assert tb.tab_factory(object(), object(), tb) == "REAL"
    finally:
        toolboxes.TOOLBOXES.remove(tb)


# ---------------------------------------------------------------------------
# Coordinates picker helpers (Tk-free; need the real survey-crs engine)
# ---------------------------------------------------------------------------

crs = pytest.importorskip("crs")


def test_search_text_finds_long_island_ftus():
    from suite import toolbox_coordinates as tc
    entries, _note = tc._search_entries(crs, "york long island",
                                       "All types", "NY")
    assert {6538, 6539} <= {e.epsg for e in entries}


def test_search_epsg_lookup():
    from suite import toolbox_coordinates as tc
    entries, _note = tc._search_entries(crs, "EPSG:6539",
                                       "All types", "All states")
    assert [e.epsg for e in entries] == [6539]
    entries, _note = tc._search_entries(crs, "6539",
                                       "All types", "All states")
    assert [e.epsg for e in entries] == [6539]


def test_browse_mode_state_filter_ny_first():
    from suite import toolbox_coordinates as tc
    entries, note = tc._search_entries(crs, "", "All types", "NY")
    assert len(entries) == 8
    assert all(e.state == "New York" for e in entries)
    assert "NY" in note


def test_type_filter_limits_to_utm():
    from suite import toolbox_coordinates as tc
    entries, _note = tc._search_entries(crs, "", "UTM", "All states")
    assert len(entries) == 120
    assert all(e.group == "utm" for e in entries)


def test_unknown_query_suggests_alternatives():
    from suite import toolbox_coordinates as tc
    entries, note = tc._search_entries(crs, "long iland",
                                      "All types", "NY")
    assert entries, "expected did-you-mean candidates"
    assert "did you mean" in note


def test_unknown_query_no_candidates():
    from suite import toolbox_coordinates as tc
    entries, note = tc._search_entries(crs, "zzzzqqqq",
                                      "All types", "NY")
    assert entries == []
    assert "No registry entry matches" in note


def test_describe_and_datum_note():
    from suite import toolbox_coordinates as tc
    e = crs.by_epsg(6539)
    text = tc._describe(e)
    assert "EPSG:6539" in text
    assert "NAD83(2011)" in text
    assert "US survey foot" in text
    assert "epsg.io/6539" in text
    note = tc._datum_note_text(e)
    assert "NAD83(2011)" in note and "EPSG:6539" in note
