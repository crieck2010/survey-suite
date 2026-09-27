"""Toolbox registry: the SurveySuite notebook is built from this registry.

A toolbox is one notebook tab. The core app (:mod:`suite.app`) builds its
notebook by iterating :func:`all_toolboxes` -- there is no hardcoded tab
list in the app. A future toolbox (e.g. a Volumes toolbox) plugs in by
dropping one ``suite/toolbox_*.py`` module into the package that calls
:func:`register_toolbox` once; the registry auto-discovers
``suite.toolbox_*`` modules at import time, so ``app.py`` never changes.

Contract for a toolbox author (see ``docs/TOOLBOXES.md`` for the full
guide):

* ``id`` -- stable string, unique across toolboxes (``"coordinates"``).
* ``title`` -- notebook tab label (``"Coordinates"``).
* ``tab_factory`` -- callable ``(app, notebook, toolbox) -> ttk.Frame``.
  It builds the tab's widgets and returns the frame; the app adds the tab
  itself under ``toolbox.title``. The factory receives the live
  ``SurveySuiteApp`` instance, so it can use ``app.project``,
  ``app.run_worker(...)``, and the other tabs' widgets -- but it must
  never ``import suite.app`` (circular). Factories must be Tk-safe:
  building widgets is fine, but no engine work at build time.
* ``engine_deps`` -- optional engine *import names* (``["crs"]``), checked
  lazily when the tab is built. When any are missing the tab is replaced
  by a "not installed" notice with a ``pip install`` hint -- the app
  still launches.
* ``description`` -- one or two sentences; shown in the notice frame and
  in docs.
* ``order`` -- sort key for notebook order (lower = further left).

This module is Tk-free except for the missing-engine notice frame, and
importing it never touches the engines.
"""
from __future__ import annotations

import dataclasses
import functools
import importlib
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional

#: tab_factory(app, notebook, toolbox) -> ttk.Frame
TabFactory = Callable[..., "ttk.Frame"]


@dataclasses.dataclass(frozen=True)
class Toolbox:
    """One notebook tab's spec. See the module docstring for the contract."""
    id: str
    title: str
    tab_factory: TabFactory
    engine_deps: tuple = ()
    description: str = ""
    order: int = 100


#: The registry itself. Prefer :func:`register_toolbox` over appending.
TOOLBOXES: List[Toolbox] = []

#: Engine import name -> pip distribution name, for the install hint.
ENGINE_PIP_NAMES: Dict[str, str] = {
    "crs": "survey-crs",
    "field": "survey-field",
    "adjustflow": "survey-adjust-workflow",
    "drafting": "survey-drafting",
    "basemap": "survey-basemap",
}


def _importable(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def missing_engine_deps(toolbox: Toolbox) -> List[str]:
    """Engine import names from ``toolbox.engine_deps`` that are not
    importable right now. [] means the tab can build."""
    return [d for d in (toolbox.engine_deps or ()) if not _importable(d)]


def _missing_deps_frame(notebook, toolbox: Toolbox,
                        missing: List[str]) -> ttk.Frame:
    frame = ttk.Frame(notebook, padding=24)
    ttk.Label(frame, text=f"{toolbox.title} — engine not installed",
              font=("TkDefaultFont", 12, "bold")).pack(anchor="w",
                                                       pady=(0, 8))
    pkgs = ", ".join(ENGINE_PIP_NAMES.get(d, d) for d in missing)
    ttk.Label(
        frame,
        text=("This toolbox needs the optional "
              f"{pkgs} engine, which is not installed "
              "in this Python environment. The rest of SurveySuite "
              "works normally."),
        wraplength=620, justify="left").pack(anchor="w")
    ttk.Label(frame,
              text=f"Install it with:\n\n    pip install {pkgs}",
              font=("TkFixedFont", 10),
              justify="left").pack(anchor="w", pady=(8, 0))
    if toolbox.description:
        ttk.Label(frame, text=toolbox.description, wraplength=620,
                  justify="left",
                  foreground="#555555").pack(anchor="w", pady=(12, 0))
    return frame


def register_toolbox(toolbox: Toolbox) -> Toolbox:
    """Add a toolbox to the registry; returns the stored spec.

    The factory is wrapped so missing ``engine_deps`` degrade to the
    "not installed" notice frame instead of raising at tab-build time.
    Raises :class:`ValueError` on a duplicate id or an invalid spec.
    """
    if not toolbox.id or not toolbox.title:
        raise ValueError("toolbox id and title must be non-empty strings")
    if any(t.id == toolbox.id for t in TOOLBOXES):
        raise ValueError(f"duplicate toolbox id: {toolbox.id!r}")
    if not callable(toolbox.tab_factory):
        raise ValueError(
            f"toolbox {toolbox.id!r}: tab_factory must be callable")
    deps = tuple(toolbox.engine_deps or ())
    orig = toolbox.tab_factory

    @functools.wraps(orig)
    def guarded(app, notebook, tb):
        missing = [d for d in deps if not _importable(d)]
        if missing:
            return _missing_deps_frame(notebook, tb, missing)
        return orig(app, notebook, tb)

    stored = dataclasses.replace(toolbox, tab_factory=guarded,
                                 engine_deps=deps)
    TOOLBOXES.append(stored)
    return stored


def all_toolboxes() -> List[Toolbox]:
    """Registered toolboxes in notebook order."""
    return sorted(TOOLBOXES, key=lambda t: (t.order, t.title))


def toolbox_by_id(toolbox_id: str) -> Optional[Toolbox]:
    for tb in TOOLBOXES:
        if tb.id == toolbox_id:
            return tb
    return None


# ---------------------------------------------------------------------------
# the six v0.2.0 workflow tabs, registered as toolboxes (build #6 refactor)
# ---------------------------------------------------------------------------

def _delegate(method_name: str):
    """Factory delegating to a SurveySuiteApp tab-builder method."""
    def build(app, notebook, toolbox):
        return getattr(app, method_name)(notebook)
    build.__name__ = f"build_{method_name}"
    return build


register_toolbox(Toolbox(
    id="project", title="Project",
    tab_factory=_delegate("_build_project_tab"),
    engine_deps=(),
    description="Project file (.sproj), surveyor profile, artifact checklist.",
    order=10))
register_toolbox(Toolbox(
    id="import", title="Import",
    tab_factory=_delegate("_build_import_tab"),
    engine_deps=("field",),
    description="Emlid CSV import and validation (survey-field).",
    order=20))
register_toolbox(Toolbox(
    id="adjust", title="Adjust",
    tab_factory=_delegate("_build_adjust_tab"),
    engine_deps=("adjustflow",),
    description="Weights editor and least-squares adjustment with the "
                "written justification report (survey-adjust-workflow).",
    order=30))
register_toolbox(Toolbox(
    id="map", title="Map",
    tab_factory=_delegate("_build_map_tab"),
    engine_deps=("field", "drafting", "basemap"),
    description="Plan-view map of job/adjusted points with optional "
                "drone basemap.",
    order=40))
register_toolbox(Toolbox(
    id="draft", title="Draft",
    tab_factory=_delegate("_build_draft_tab"),
    engine_deps=("drafting",),
    description="Parcel builder and plat/plan/map PDF composer "
                "(survey-drafting).",
    order=50))
register_toolbox(Toolbox(
    id="basemap", title="Basemap",
    tab_factory=_delegate("_build_basemap_tab"),
    engine_deps=("basemap",),
    description="Drone orthomosaic (GeoTIFF) info, GSD check, overviews, "
                "project attach (survey-basemap).",
    order=60))


def _discover_toolbox_modules() -> None:
    """Import every ``suite.toolbox_*`` module so it can self-register.

    This is what lets a future toolbox plug in without touching
    ``app.py`` (or this module): drop the module in, it calls
    :func:`register_toolbox` at import, and the notebook picks it up.
    """
    import pkgutil
    import suite as _suite_pkg
    for info in pkgutil.iter_modules(_suite_pkg.__path__):
        if info.name.startswith("toolbox_"):
            importlib.import_module(f"suite.{info.name}")


_discover_toolbox_modules()
