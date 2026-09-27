"""Smoke tests for the SurveySuite v0.3.0 desktop app (suite.app).

Import-level tests must pass headless. GUI construction tests are
SKIPPED when there is no display ($DISPLAY unset) -- they never fail
headless. Run with: python3 -m pytest tests/test_app_smoke.py
"""
import os

import pytest


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY"))


def test_import_app_without_display():
    """Importing suite.app must not create Tk objects or need a display."""
    import suite.app as app  # noqa: F401


def test_main_and_build_app_callable():
    import suite.app as app
    assert callable(app.main)
    assert callable(app.build_app)


def test_parse_grid_kept():
    from suite.app import parse_grid
    assert parse_grid("1,2;3,4") == [[1.0, 2.0], [3.0, 4.0]]
    with pytest.raises(ValueError):
        parse_grid("1,2;3")


def test_runners_api_surface():
    """The orchestration API the GUI depends on is importable and Tk-free."""
    from suite import runners
    for name in ("run_import", "default_weights", "validate_weights",
                 "weights_summary", "run_adjust", "read_report",
                 "style_template", "validate_style", "parcel_template",
                 "run_draft", "basemap_info", "build_basemap_overviews",
                 "gsd_check", "make_basemap_source", "map_points",
                 "map_extent"):
        assert callable(getattr(runners, name)), name


def test_sheet_choices_match_contract():
    from suite.app import SHEET_CHOICES
    assert set(SHEET_CHOICES) == {"ANSI_A", "ANSI_B", "ANSI_C", "ANSI_D",
                                 "ANSI_E", "ARCH_C", "ARCH_D"}


def test_mapview_import_without_display():
    import suite.mapview as mapview  # noqa: F401
    assert hasattr(mapview, "SurveyMapView")
    assert hasattr(mapview, "photoimage_from_rgb")


@pytest.mark.skipif(not _has_display(),
                    reason="GUI construction needs a display ($DISPLAY)")
def test_build_app_constructs():
    from suite.app import build_app
    app = build_app()
    try:
        assert app._notebook.tabs(), "expected notebook tabs"
    finally:
        app.destroy()


@pytest.mark.skipif(not _has_display(),
                    reason="GUI construction needs a display ($DISPLAY)")
def test_mapview_constructs():
    import tkinter as tk
    from suite.mapview import SurveyMapView
    root = tk.Tk()
    try:
        view = SurveyMapView(root)
        view.pack()
        view.set_data([])  # no-data path must not crash
        view.show_basemap(True)
        view.fit()
    finally:
        root.destroy()


@pytest.mark.skipif(not _has_display(),
                    reason="GUI construction needs a display ($DISPLAY)")
def test_seven_toolbox_tabs_from_registry():
    """Build #6: notebook tabs come from the toolbox registry -- titles
    in registry order, frames keyed by stable toolbox id. There is no
    hardcoded tab list in the app."""
    from suite import toolboxes
    from suite.app import build_app
    app = build_app()
    try:
        titles = [app._notebook.tab(t, "text")
                  for t in app._notebook.tabs()]
        assert titles == [t.title for t in toolboxes.all_toolboxes()]
        assert titles == ["Project", "Import", "Adjust", "Map", "Draft",
                          "Basemap", "Coordinates"]
        assert (set(app._toolbox_frames)
                == {t.id for t in toolboxes.all_toolboxes()})
        for tab_id in ("project", "import", "adjust", "map", "draft",
                       "basemap", "coordinates"):
            app.select_toolbox(tab_id)  # must not raise
    finally:
        app.destroy()


@pytest.mark.skipif(not _has_display(),
                    reason="GUI construction needs a display ($DISPLAY)")
def test_coordinates_picker_flow(tmp_path, monkeypatch):
    """Coordinates toolbox end to end: search the real survey-crs
    registry -> select -> Set as project CRS (pending, no project open)
    -> new project captures it -> reproject toggle threads the target
    into Import."""
    pytest.importorskip("crs")
    import tkinter.messagebox as _mb
    monkeypatch.setattr(_mb, "showinfo", lambda *a, **k: "ok")
    monkeypatch.setattr(_mb, "showerror", lambda *a, **k: "ok")
    from suite.app import build_app
    app = build_app()
    try:
        app.coords_query_var.set("york long island")
        app.coords_do_search()
        app.update()
        assert app.coords_results.size() >= 2
        app.coords_results.selection_set(0)
        entry = app.coords_selected_entry()
        assert entry is not None and entry.epsg in (6538, 6539)

        # no project open: staged as pending CRS text
        app.coords_set_project_crs()
        app.update()
        assert "Long Island" in app.proj_crs.get()
        assert str(app.proj_crs.cget("state")) == "readonly"

        # creating the project captures the pending picker selection
        app.proj_name.delete(0, "end")
        app.proj_name.insert(0, "CRStest")
        app.proj_dir.delete(0, "end")
        app.proj_dir.insert(0, str(tmp_path))
        app._new_project()
        app.update()
        assert "Long Island" in app.project.crs
        assert app.proj_crs.get() == app.project.crs
        assert "Long Island" in app.coord_target_var.get()

        # reproject toggle -> Import status + runner target
        app.coord_reproject_var.set(True)
        app.refresh_import_crs_status()
        app.refresh_coords_crs_display()
        app.update()
        assert "ON" in app.import_crs_status.get()
        assert "Long Island" in app.import_crs_status.get()
        assert app._import_target_crs() == app.project.crs

        app.coord_reproject_var.set(False)
        app.refresh_import_crs_status()
        assert app._import_target_crs() is None
        assert "OFF" in app.import_crs_status.get()
    finally:
        app.destroy()
