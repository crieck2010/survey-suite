"""Smoke tests for the SurveySuite v0.2.0 desktop app (suite.app).

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
