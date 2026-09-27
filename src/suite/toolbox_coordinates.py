"""Coordinates toolbox: CRS picker over the optional survey-crs engine.

The first toolbox built natively on the :mod:`suite.toolboxes` registry
pattern (build #6): text search, EPSG lookup, group-by-type and state
filters over survey-crs's 345-entry registry, position-based suggestions
via ``crs.suggest(lat, lon)``, a "did you mean ...?" fallback for queries
with no hits (token-drop over ``crs.search`` -- survey-crs has no
string-similarity API, so this is implemented honestly at the UI layer),
datum/EPSG/unit/area-of-use details for the selection, "Set as project
CRS" (writes ``project.crs``, persisted in the ``.sproj``), an editable
datum-note field with a "Copy to Draft tab" button, and the
reproject-on-import toggle wired into the Import tab's runner.

``survey-crs`` is optional: the registry wraps this factory so the tab
degrades to a "pip install survey-crs" notice when the engine is absent.
The module itself imports ``crs`` lazily (inside functions) so importing
this module never fails for a missing engine.
"""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk

from suite.toolboxes import Toolbox, register_toolbox

#: Matches "EPSG:6539", "epsg: 6539", or a bare "6539".
_EPSG_RE = re.compile(r"^\s*(?:epsg\s*:\s*)?(\d{1,6})\s*$", re.IGNORECASE)

#: Postal abbreviations accepted by survey-crs's zones_for_state().
STATES = ["All states",
          "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
          "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA",
          "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
          "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
          "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR"]

#: (combobox label, survey-crs group key or None for "all").
TYPES = [("All types", None), ("SPCS", "spcs"), ("UTM", "utm"),
         ("Geographic", "geographic")]

MAX_RESULTS = 200


def _import_crs():
    """Lazily import the optional survey-crs engine."""
    try:
        import crs  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "The Coordinates toolbox needs the survey-crs engine, which "
            "is not installed. Install it with:\n"
            "    pip install survey-crs\n"
            "(https://github.com/crieck2010/survey-crs)") from exc
    return crs


def _set_text(widget: tk.Text, text: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    widget.configure(state="disabled")


def _did_you_mean(crs_mod, query: str):
    """Fallback for queries with no hits: search each token alone and
    offer the union as "did you mean ...?" candidates."""
    seen, out = set(), []
    for token in query.strip().lower().split():
        if len(token) < 2:
            continue
        for hit in crs_mod.search(token, limit=5):
            if hit.epsg not in seen:
                seen.add(hit.epsg)
                out.append(hit)
                if len(out) >= 8:
                    return out
    return out


def _search_entries(crs_mod, query: str, type_label: str, state_abbr: str):
    """Run the picker query; returns (entries, note)."""
    group = dict(TYPES)[type_label]
    if not query:
        # browse mode: the state's SPCS zones (NY first by default), or
        # the whole registry grouped and EPSG-sorted.
        if state_abbr != "All states":
            entries = list(crs_mod.zones_for_state(state_abbr))
            note = f"{len(entries)} SPCS zone(s) for {state_abbr}"
        else:
            entries = []
            for grp in crs_mod.group_by_type().values():
                entries.extend(grp)
            entries.sort(key=lambda e: e.epsg)
            note = f"{len(entries)} registry entries"
    else:
        m = _EPSG_RE.match(query)
        if m:
            try:
                return [crs_mod.by_epsg(int(m.group(1)))], ""
            except Exception:  # noqa: BLE001 -- fall through to text search
                pass
        entries = crs_mod.search(query, limit=MAX_RESULTS)
        note = ""
    if group is not None:
        entries = [e for e in entries if e.group == group]
    if query and state_abbr != "All states":
        state_epsgs = {e.epsg
                       for e in crs_mod.zones_for_state(state_abbr)}
        entries = [e for e in entries if e.epsg in state_epsgs]
    if query and not entries:
        guesses = _did_you_mean(crs_mod, query)
        if guesses:
            return guesses, (f"No exact match for {query!r} -- "
                             "did you mean one of these?")
        return [], f"No registry entry matches {query!r}."
    if not note:
        note = (f"{len(entries)} result(s)"
                + (" (list truncated -- refine the search)"
                   if len(entries) >= MAX_RESULTS else ""))
    return entries, note


def _describe(entry) -> str:
    lines = [f"{entry.name}  (EPSG:{entry.epsg})",
             f"datum: {entry.datum}",
             f"kind: {entry.kind}   unit: {entry.unit_label}",
             f"area of use: {entry.area_name}"]
    if entry.state or entry.zone:
        lines.append("state/zone: %s" % " / ".join(
            p for p in (entry.state, entry.zone) if p))
    lines.append(f"source: {entry.source_url}")
    if entry.notes:
        lines.append(f"notes: {entry.notes}")
    return "\n".join(lines)


def _datum_note_text(entry) -> str:
    return (f"Horizontal datum: {entry.datum}. Coordinates are in "
            f"{entry.name} (EPSG:{entry.epsg}), "
            f"{entry.unit_label.lower()}.")


def _build_coordinates_tab(app, notebook, toolbox):  # noqa: C901 -- UI layout
    crs_mod = _import_crs()
    frame = ttk.Frame(notebook, padding=10)

    # -- search row -----------------------------------------------------
    srow = ttk.Frame(frame)
    srow.pack(fill="x")
    srow.columnconfigure(0, weight=1)
    query_var = tk.StringVar()
    qentry = ttk.Entry(srow, textvariable=query_var)
    qentry.grid(row=0, column=0, sticky="ew")
    ttk.Button(srow, text="Search",
               command=lambda: do_search()).grid(row=0, column=1,
                                                 padx=(6, 0))

    # -- filter row -----------------------------------------------------
    frow = ttk.Frame(frame)
    frow.pack(fill="x", pady=(6, 0))
    ttk.Label(frow, text="Type:").pack(side="left")
    type_var = tk.StringVar(value="All types")
    tcombo = ttk.Combobox(frow, textvariable=type_var, state="readonly",
                          values=[t[0] for t in TYPES], width=12)
    tcombo.pack(side="left", padx=(4, 12))
    ttk.Label(frow, text="State:").pack(side="left")
    state_var = tk.StringVar(value="NY")
    scombo = ttk.Combobox(frow, textvariable=state_var, state="readonly",
                          values=STATES, width=10)
    scombo.pack(side="left", padx=(4, 0))

    # -- position-suggest row -------------------------------------------
    grow = ttk.Frame(frame)
    grow.pack(fill="x", pady=(6, 0))
    ttk.Label(grow, text="Suggest for position — lat:").pack(side="left")
    lat_var, lon_var = tk.StringVar(), tk.StringVar()
    ttk.Entry(grow, textvariable=lat_var, width=10).pack(side="left",
                                                        padx=(4, 2))
    ttk.Label(grow, text="lon:").pack(side="left")
    ttk.Entry(grow, textvariable=lon_var, width=10).pack(side="left",
                                                        padx=(4, 2))
    ttk.Button(grow, text="Suggest",
               command=lambda: do_suggest()).pack(side="left", padx=(6, 0))

    # -- results + details ----------------------------------------------
    mid = ttk.Frame(frame)
    mid.pack(fill="both", expand=True, pady=(8, 0))
    mid.columnconfigure(0, weight=1)
    mid.columnconfigure(1, weight=1)
    left = ttk.Frame(mid)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    left.columnconfigure(0, weight=1)
    left.rowconfigure(0, weight=1)
    right = ttk.Frame(mid)
    right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
    right.columnconfigure(0, weight=1)
    right.rowconfigure(1, weight=1)
    mid.rowconfigure(0, weight=1)

    results = tk.Listbox(left, height=14)
    results.grid(row=0, column=0, sticky="nsew")
    status_var = tk.StringVar(value="")
    ttk.Label(left, textvariable=status_var, foreground="#555555",
              wraplength=420, justify="left").grid(row=1, column=0,
                                                   sticky="w", pady=(4, 0))
    ttk.Label(right, text="Selection:").grid(row=0, column=0, sticky="w")
    details = tk.Text(right, height=14, width=48, wrap="word",
                      state="disabled")
    details.grid(row=1, column=0, sticky="nsew")

    shown: list = []

    def show(entries, note):
        shown.clear()
        shown.extend(entries)
        results.delete(0, "end")
        for e in entries[:MAX_RESULTS]:
            results.insert("end", f"{e.name}  (EPSG:{e.epsg})")
        status_var.set(note)

    def selected_entry():
        sel = results.curselection()
        return shown[sel[0]] if sel else None

    def on_select(_event=None):
        e = selected_entry()
        if e is None:
            return
        _set_text(details, _describe(e))
        note_text.configure(state="normal")
        note_text.delete("1.0", "end")
        note_text.insert("1.0", _datum_note_text(e))
        note_text.configure(state="normal")  # stays editable

    results.bind("<<ListboxSelect>>", on_select)

    def do_search():
        try:
            entries, note = _search_entries(
                crs_mod, query_var.get().strip(), type_var.get(),
                state_var.get())
        except Exception as exc:  # noqa: BLE001 -- engine-level error
            status_var.set(f"Search failed: {exc}")
            return
        show(entries, note)
        if entries:
            results.selection_set(0)
            on_select()

    def do_suggest():
        try:
            lat = float(lat_var.get().strip())
            lon = float(lon_var.get().strip())
        except ValueError:
            status_var.set("Suggest needs numeric lat/lon in degrees.")
            return
        try:
            entries = crs_mod.suggest(lat, lon)
        except Exception as exc:  # noqa: BLE001
            status_var.set(f"Suggest failed: {exc}")
            return
        show(entries, f"{len(entries)} suggestion(s) for {lat}, {lon} "
                      "(SPCS zones containing the point, then UTM)")
        if entries:
            results.selection_set(0)
            on_select()

    qentry.bind("<Return>", lambda _e: do_search())
    tcombo.bind("<<ComboboxSelected>>", lambda _e: do_search())
    scombo.bind("<<ComboboxSelected>>", lambda _e: do_search())

    # -- datum note ------------------------------------------------------
    nbox = ttk.LabelFrame(frame, text="Datum note", padding=6)
    nbox.pack(fill="x", pady=(8, 0))
    nbox.columnconfigure(0, weight=1)
    note_text = tk.Text(nbox, height=3, width=70, wrap="word")
    note_text.grid(row=0, column=0, sticky="ew")
    ttk.Button(nbox, text="Copy to Draft tab",
               command=lambda: copy_to_draft()).grid(row=0, column=1,
                                                     padx=(6, 0))

    def copy_to_draft():
        target = getattr(app, "draft_datum", None)
        if target is None:
            messagebox.showinfo(
                "Datum note",
                "The Draft tab is not available (drafting engine "
                "missing?).")
            return
        target.delete(0, "end")
        target.insert(0, note_text.get("1.0", "end").strip())
        messagebox.showinfo("Datum note",
                            "Copied into the Draft tab's datum note field.")

    # -- actions ----------------------------------------------------------
    act = ttk.Frame(frame)
    act.pack(fill="x", pady=(8, 0))
    ttk.Button(act, text="Set as project CRS",
               command=lambda: set_project_crs()).pack(side="left",
                                                       padx=(0, 8))
    ttk.Button(act, text="Go to Project tab",
               command=lambda: app.select_toolbox("project")).pack(
                   side="left")

    def set_project_crs():
        e = selected_entry()
        if e is None:
            messagebox.showinfo("Project CRS",
                                "Select a CRS from the results first.")
            return
        proj = app.project
        if proj is not None:
            proj.crs = e.name
            proj.save()
            app._sync_proj_crs_display()
            app.refresh_coords_crs_display()
            app.refresh_import_crs_status()
            messagebox.showinfo(
                "Project CRS",
                f"Project CRS set to:\n{e.name} (EPSG:{e.epsg})\n\n"
                "Saved in the .sproj manifest.")
        else:
            app._set_proj_crs_text(e.name)
            messagebox.showinfo(
                "Project CRS",
                f"No project open -- this CRS will be used when you "
                f"create the next project:\n{e.name} (EPSG:{e.epsg})")

    # -- reproject on import ----------------------------------------------
    rbox = ttk.LabelFrame(frame, text="Reproject on import", padding=6)
    rbox.pack(fill="x", pady=(8, 0))
    app.coord_reproject_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        rbox,
        text="Reproject geographic imports to the project CRS on import "
             "(survey-field --target-crs)",
        variable=app.coord_reproject_var,
        command=lambda: (app.refresh_import_crs_status(),
                         app.refresh_coords_crs_display())).pack(anchor="w")
    app.coord_target_var = tk.StringVar()
    ttk.Label(rbox, textvariable=app.coord_target_var,
              foreground="#555555", wraplength=700,
              justify="left").pack(anchor="w", pady=(4, 0))
    app.refresh_coords_crs_display()

    # handles for tests / cross-tab scripting (absent when the crs
    # engine is missing and the notice frame is built instead)
    app.coords_query_var = query_var
    app.coords_type_var = type_var
    app.coords_state_var = state_var
    app.coords_lat_var = lat_var
    app.coords_lon_var = lon_var
    app.coords_results = results
    app.coords_do_search = do_search
    app.coords_do_suggest = do_suggest
    app.coords_set_project_crs = set_project_crs
    app.coords_selected_entry = selected_entry

    # initial view: NY zones first
    do_search()
    return frame


register_toolbox(Toolbox(
    id="coordinates",
    title="Coordinates",
    tab_factory=_build_coordinates_tab,
    engine_deps=("crs",),
    description=("CRS picker over the survey-crs registry (345 entries): "
                 "search, EPSG lookup, SPCS/UTM/geographic grouping, state "
                 "filter, position suggestions, project-CRS assignment, and "
                 "reproject-on-import."),
    order=70))
