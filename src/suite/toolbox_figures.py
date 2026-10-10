"""Figures toolbox: field-coded linework over the survey-linework engine.

Civil 3D Toolspace model: the left panel is the figure tree (Prospector's
item lists -- click a figure to select and zoom), the right panel is the
map canvas with figures drawn as linework, and the bottom panel is the QA
panel showing the validation report with plain-language explanations.
Strict mode refuses flagged linework from reaching drafting -- problems
are surfaced, never hidden.

``survey-linework`` is optional: the registry wraps this factory so the
tab degrades to a "pip install" notice when the engine is absent. The
module imports the engine lazily (inside functions) so importing this
module never fails for a missing engine. All figure math stays in the
engine; Tk-free orchestration lives in :mod:`suite.runners`.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from suite.toolboxes import Toolbox, register_toolbox

#: code-set choices in the picker; the trailing entry opens a file dialog.
CODESET_CHOICES = ["preset:emlid", "preset:civil3d", "JSON file..."]

DEFAULT_SAGITTA_M = 0.01


def _import_linework():
    """Lazily import the optional survey-linework engine."""
    try:
        import linework  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "The Figures toolbox needs the survey-linework engine, which "
            "is not installed. Install it with:\n"
            "    pip install survey-linework\n"
            "(https://github.com/crieck2010/survey-linework)") from exc
    return linework


def _set_text(widget: tk.Text, text: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    widget.configure(state="disabled")


def _fmt_m(value) -> str:
    if value is None:
        return "--"
    return f"{value:.3f} m"


def _fmt_area(value) -> str:
    if value is None:
        return "--"
    return f"{value:.2f} m^2"


# ---------------------------------------------------------------------------
# Tk-free helpers (unit-testable)
# ---------------------------------------------------------------------------

def summarize_figures(figures_data: dict) -> dict:
    """Counts + flag totals for the QA header, Tk-free."""
    from suite import runners
    recs = runners.figure_records(figures_data)
    flags = runners.qa_flag_list(figures_data)
    return {
        "n_figures": len(recs),
        "n_closed": sum(1 for r in recs if r["closed"]),
        "n_open": sum(1 for r in recs if not r["closed"]),
        "n_flagged": sum(1 for r in recs if r["n_flags"]),
        "n_flags": len([f for f in flags if f["flag"] != "warning"]),
        "n_warnings": len([f for f in flags if f["flag"] == "warning"]),
        "codeset": (figures_data.get("codeset") or {}).get("name", "?"),
    }


def figure_extent(fig_canvas: list, figure_id: str):
    """(xmin, ymin, xmax, ymax) for one figure's canvas polyline."""
    for fig in fig_canvas:
        if fig["id"] == figure_id and fig["pts"]:
            xs = [p[0] for p in fig["pts"]]
            ys = [p[1] for p in fig["pts"]]
            return (min(xs), min(ys), max(xs), max(ys))
    return None


def _build_figures_tab(app, notebook, toolbox):  # noqa: C901 -- UI layout
    _import_linework()  # the registry already checked; import for use below
    from suite import runners
    from suite.mapview import SurveyMapView

    frame = ttk.Frame(notebook, padding=6)

    # -- toolbar ---------------------------------------------------------
    bar = ttk.Frame(frame)
    bar.pack(fill="x", pady=(0, 6))

    build_btn = ttk.Button(bar, text="Build figures from job")
    build_btn.pack(side="left", padx=(0, 8))

    ttk.Label(bar, text="Code set:").pack(side="left")
    codeset_var = tk.StringVar(value="preset:emlid")
    codeset_combo = ttk.Combobox(bar, textvariable=codeset_var,
                                 state="readonly", width=16,
                                 values=CODESET_CHOICES)
    codeset_combo.pack(side="left", padx=(4, 10))

    ttk.Label(bar, text="Sagitta (m):").pack(side="left")
    sagitta_var = tk.StringVar(value=str(DEFAULT_SAGITTA_M))
    sagitta_entry = ttk.Entry(bar, textvariable=sagitta_var, width=7)
    sagitta_entry.pack(side="left", padx=(4, 10))

    strict_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(bar, text="Strict: refuse flagged linework in Draft",
                    variable=strict_var).pack(side="left", padx=(0, 10))
    in_draft_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(bar, text="Include figures in plat PDF",
                    variable=in_draft_var).pack(side="left", padx=(0, 10))

    refresh_btn = ttk.Button(bar, text="Refresh")
    refresh_btn.pack(side="left")

    status_var = tk.StringVar(value="No figures built yet.")
    ttk.Label(bar, textvariable=status_var, foreground="#555555").pack(
        side="right", padx=4)

    # -- main split: tree+properties | canvas -----------------------------
    paned = ttk.PanedWindow(frame, orient="horizontal")
    paned.pack(fill="both", expand=True)

    left = ttk.Frame(paned)
    paned.add(left, weight=1)
    left.columnconfigure(0, weight=1)
    left.rowconfigure(0, weight=3)
    left.rowconfigure(1, weight=2)

    tree = ttk.Treeview(left, columns=("verts", "length", "status"),
                        show="tree headings", height=12)
    tree.heading("#0", text="Figure")
    tree.heading("verts", text="Verts")
    tree.heading("length", text="Length")
    tree.heading("status", text="Status")
    tree.column("#0", width=150)
    tree.column("verts", width=55, anchor="e")
    tree.column("length", width=90, anchor="e")
    tree.column("status", width=110)
    tree.grid(row=0, column=0, sticky="nsew", pady=(0, 6))

    props = tk.Text(left, height=10, width=40, wrap="word", state="disabled")
    props.grid(row=1, column=0, sticky="nsew")
    ttk.Label(left, text="Figure properties",
              foreground="#555555").grid(row=2, column=0, sticky="w")

    right = ttk.Frame(paned)
    paned.add(right, weight=3)
    canvas = SurveyMapView(right)
    canvas.pack(fill="both", expand=True)

    # -- QA panel ----------------------------------------------------------
    qa_box = ttk.LabelFrame(frame, text="QA -- validation report", padding=6)
    qa_box.pack(fill="x", pady=(6, 0))
    qa_box.columnconfigure(0, weight=3)
    qa_box.columnconfigure(1, weight=2)

    qa_tree = ttk.Treeview(qa_box, columns=("detail",), show="tree headings",
                           height=5)
    qa_tree.heading("#0", text="Flag")
    qa_tree.heading("detail", text="Detail")
    qa_tree.column("#0", width=220)
    qa_tree.column("detail", width=420)
    qa_tree.grid(row=0, column=0, sticky="ew", padx=(0, 6))

    qa_right = ttk.Frame(qa_box)
    qa_right.grid(row=0, column=1, sticky="nsew")
    qa_right.columnconfigure(0, weight=1)
    qa_right.rowconfigure(0, weight=1)
    qa_text = tk.Text(qa_right, height=5, width=50, wrap="word",
                      state="disabled")
    qa_text.grid(row=0, column=0, sticky="nsew")
    qa_btns = ttk.Frame(qa_right)
    qa_btns.grid(row=1, column=0, sticky="ew", pady=(4, 0))
    zoom_btn = ttk.Button(qa_btns, text="Zoom to figure")
    zoom_btn.pack(side="left")

    # -- state --------------------------------------------------------------
    state = {"data": None, "canvas": [], "selected": None,
             "codeset_file": None}

    def sagitta() -> float:
        try:
            v = float(sagitta_var.get().strip())
        except ValueError:
            raise ValueError("Sagitta must be a number in metres.")
        if v <= 0:
            raise ValueError("Sagitta must be positive.")
        return v

    def codeset_source() -> str:
        choice = codeset_var.get()
        if choice == "JSON file...":
            path = filedialog.askopenfilename(
                title="Linework code-set JSON",
                filetypes=[("JSON", "*.json"), ("All files", "*.*")])
            if not path:
                raise ValueError("No code-set file chosen.")
            state["codeset_file"] = path
            return path
        state["codeset_file"] = None
        return choice

    def refresh_all():
        """Reload figures from the project manifest into tree/canvas/QA."""
        proj = app.project
        if proj is None or not proj.artifact_exists("figures_path"):
            state["data"] = None
            state["canvas"] = []
            tree.delete(*tree.get_children())
            canvas.clear_linework()
            qa_tree.delete(*qa_tree.get_children())
            _set_text(qa_text, "")
            _set_text(props, "")
            status_var.set("No figures built yet.")
            return
        try:
            data = runners.read_figures(proj.resolve(proj.figures_path))
        except Exception as exc:  # noqa: BLE001 -- surface, don't crash
            status_var.set(f"Could not read figures: {exc}")
            return
        state["data"] = data
        try:
            sg = sagitta()
        except ValueError:
            sg = DEFAULT_SAGITTA_M
        state["canvas"] = runners.figures_canvas_data(data,
                                                      chord_sagitta_m=sg)
        _fill_tree()
        _draw_canvas()
        _fill_qa()
        summ = summarize_figures(data)
        status_var.set(
            f"{summ['n_figures']} figure(s): {summ['n_closed']} closed, "
            f"{summ['n_open']} open, {summ['n_flags']} flag(s) "
            f"(code set: {summ['codeset']})")

    def _fill_tree():
        tree.delete(*tree.get_children())
        data = state["data"]
        if data is None:
            return
        groups = {}
        for grp_id, label in (("closed", "Closed figures"),
                              ("open", "Open figures")):
            groups[grp_id] = tree.insert("", "end", text=label, open=True)
        for rec in runners.figure_records(data):
            mark = "⚠ " if rec["n_flags"] else ("✔ " if rec["closed"]
                                                else "")
            status = ("flagged (%d)" % rec["n_flags"] if rec["n_flags"]
                      else ("closed" if rec["closed"] else "open"))
            try:
                stats = runners.figure_stats(data, rec["id"],
                                             chord_sagitta_m=DEFAULT_SAGITTA_M)
                length = f"{stats['length_m']:.2f} m"
            except Exception:  # noqa: BLE001 -- tree must always fill
                length = "--"
            parent = groups["closed" if rec["closed"] else "open"]
            tree.insert(parent, "end", iid=rec["id"],
                        text=f"{mark}{rec['id']}",
                        values=(rec["n_vertices"], length, status))

    def _draw_canvas():
        items = []
        for fig in state["canvas"]:
            items.append({"id": fig["id"], "pts": fig["pts"],
                          "closed": fig["closed"],
                          "selected": fig["id"] == state["selected"]})
        canvas.set_linework(items)

    def _fill_qa():
        qa_tree.delete(*qa_tree.get_children())
        data = state["data"]
        if data is None:
            return
        for fl in runners.qa_flag_list(data):
            label = (f"[{fl['figure']}] {fl['flag']}"
                     if fl["figure"] else fl["flag"])
            qa_tree.insert("", "end", text=label,
                           values=(fl["detail"],),
                           tags=(fl["figure"],))

    def show_properties(figure_id: str):
        data = state["data"]
        if data is None:
            return
        try:
            st = runners.figure_stats(data, figure_id,
                                      chord_sagitta_m=sagitta())
        except Exception as exc:  # noqa: BLE001
            _set_text(props, f"Could not compute stats: {exc}")
            return
        lines = [
            f"Figure: {st['id']}",
            f"Layer: {st['layer']}   style: {st['style']}",
            f"Vertices: {st['n_vertices']} "
            f"(chorded: {st['n_chorded']} at {sagitta_var.get()} m)",
            f"Length: {_fmt_m(st['length_m'])}",
            f"Closed: {'yes (' + st['close_method'] + ')' if st['closed'] else 'no'}",
            f"Misclosure: {_fmt_m(st['misclosure_m'])}",
        ]
        if st["closed"]:
            lines.append(f"Area: {_fmt_area(st['area_m2'])}")
            lines.append(f"Perimeter: {_fmt_m(st['perimeter_m'])}")
        if st["offset_of"]:
            lines.append(f"Offset of: {st['offset_of']}")
        prov = st.get("provenance") or {}
        lines.append("")
        lines.append("Provenance:")
        lines.append(f"  code set: {prov.get('codeset_name', '?')} "
                     f"v{prov.get('codeset_version', '?')}")
        lines.append(f"  job sha256: {str(prov.get('job_sha256', ''))[:12]}…")
        _set_text(props, "\n".join(lines))

    def on_tree_select(_event=None):
        sel = tree.selection()
        if not sel or sel[0] in ("closed", "open"):
            return
        state["selected"] = sel[0]
        _draw_canvas()
        show_properties(sel[0])

    tree.bind("<<TreeviewSelect>>", on_tree_select)

    def on_qa_select(_event=None):
        sel = qa_tree.selection()
        if not sel:
            return
        item = qa_tree.item(sel[0])
        text = item["text"]
        detail = item["values"][0] if item["values"] else ""
        figure = (item["tags"] or [""])[0]
        data = state["data"]
        explanation = ""
        if data is not None:
            for fl in runners.qa_flag_list(data):
                key = (f"[{fl['figure']}] {fl['flag']}"
                       if fl["figure"] else fl["flag"])
                if key == text:
                    explanation = fl["explanation"]
                    break
        _set_text(qa_text,
                  f"{text}\n{detail}\n\nWhy this matters:\n{explanation}")
        state["qa_figure"] = figure

    qa_tree.bind("<<TreeviewSelect>>", on_qa_select)

    def do_zoom_to_figure():
        fig_id = state.get("qa_figure") or state.get("selected")
        if not fig_id:
            messagebox.showinfo("Zoom", "Select a figure or a QA flag first.")
            return
        ext = figure_extent(state["canvas"], fig_id)
        if ext is None:
            messagebox.showinfo("Zoom", f"No geometry for {fig_id}.")
            return
        canvas.zoom_to_extent(ext)
        app.select_toolbox("figures")

    def do_build():
        proj = app.project
        if proj is None:
            messagebox.showinfo("Build figures",
                                "Create or open a project first "
                                "(Project tab).")
            return
        if not proj.artifact_exists("job_path"):
            messagebox.showinfo("Build figures",
                                "Import a job first (Import tab) -- figures "
                                "are built from the coded .sfield.json job.")
            return
        try:
            src = codeset_source()
            sg = sagitta()
        except ValueError as exc:
            messagebox.showerror("Build figures", str(exc))
            return
        job = proj.resolve(proj.job_path)
        out = os.path.join(proj.root, f"{proj.name}.figures.json")

        def work():
            return runners.run_figures_build(
                job, src, out,
                keys_path=proj.keys_path and proj.resolve(proj.keys_path),
                prefixes_path=(proj.prefixes_path
                               and proj.resolve(proj.prefixes_path)),
                offset_sagitta_m=sg)

        def done(res: runners.FiguresBuildResult):
            proj.set_artifact("figures_path", res.figures_path)
            proj.codeset_source = src
            proj.figures_strict = bool(strict_var.get())
            proj.figures_in_draft = bool(in_draft_var.get())
            proj.save()
            refresh_all()
            app.refresh_map()  # the Map tab can overlay linework too
            msg = (f"Built {res.counts['n_figures']} figure(s) "
                   f"({res.counts['n_closed_figures']} closed) from "
                   f"{res.counts['n_coded_points']} coded points.\n"
                   f"{res.counts['n_flags']} flag(s).")
            if res.flags:
                msg += ("\n\nReview the QA panel before drafting -- strict "
                        "mode refuses flagged linework from the plat.")
            messagebox.showinfo("Build figures", msg)

        def err(exc):
            messagebox.showerror("Build figures",
                                 f"Figure build failed (fail loud):\n{exc}")

        app.run_worker(work, done, on_error=err, busy=[build_btn])

    def do_send_to_draft():
        """Stage the current figures for the Draft tab, gated by strict."""
        proj = app.project
        if proj is None or not proj.artifact_exists("figures_path"):
            messagebox.showinfo("Send to Draft", "Build figures first.")
            return
        proj.figures_strict = bool(strict_var.get())
        proj.figures_in_draft = True
        in_draft_var.set(True)
        proj.save()
        messagebox.showinfo(
            "Send to Draft",
            "Figures will be included on the linework layer the next time "
            "you compose in the Draft tab.\n\n"
            + ("Strict mode is ON: flagged linework will refuse to draft."
               if proj.figures_strict else
               "Strict mode is OFF: flagged linework will draft anyway."))

    build_btn.configure(command=do_build)
    refresh_btn.configure(command=refresh_all)
    zoom_btn.configure(command=do_zoom_to_figure)

    def on_strict_toggle():
        proj = app.project
        if proj is not None:
            proj.figures_strict = bool(strict_var.get())
            proj.save()

    def on_in_draft_toggle():
        proj = app.project
        if proj is not None:
            proj.figures_in_draft = bool(in_draft_var.get())
            proj.save()

    strict_var.trace_add("write", lambda *_a: on_strict_toggle())
    in_draft_var.trace_add("write", lambda *_a: on_in_draft_toggle())

    def sync_from_project():
        proj = app.project
        if proj is not None:
            codeset_var.set(proj.codeset_source or "preset:emlid")
            strict_var.set(bool(proj.figures_strict))
            in_draft_var.set(bool(proj.figures_in_draft))

    # handles for tests / cross-tab scripting
    app.figures_state = state
    app.figures_do_build = do_build
    app.figures_refresh = refresh_all
    app.figures_send_to_draft = do_send_to_draft
    app.figures_sync_from_project = sync_from_project
    app.figures_codeset_var = codeset_var
    app.figures_strict_var = strict_var
    app.figures_in_draft_var = in_draft_var
    app.figures_tree = tree
    app.figures_qa_tree = qa_tree
    app.figures_canvas = canvas

    sync_from_project()
    refresh_all()
    return frame


register_toolbox(Toolbox(
    id="figures",
    title="Figures",
    tab_factory=_build_figures_tab,
    engine_deps=("linework", "cogo", "field"),
    description=("Field-coded linework (survey-linework): figure tree, "
                 "map canvas overlay, QA panel with plain-language flag "
                 "explanations, and a strict gate before figures reach "
                 "drafting."),
    order=45))
