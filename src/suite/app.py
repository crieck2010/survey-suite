"""SurveySuite desktop application (v0.2.0).

Thin tkinter UI over the survey-suite product engines. Every button calls
:mod:`suite.runners` -- the GUI never calls the engines directly and
contains no surveying math.

Importing this module is side-effect free (no Tk objects are created);
call :func:`main` to launch.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from suite import __version__
from suite import runners
from suite.licensing import check_license, license_required
from suite.mapview import SurveyMapView, photoimage_from_rgb
from suite.project import SurveyProject, recent_projects, remember_project
from suite.updates import check_for_updates

# Sheet choices come from the drafting engine's layout registry; fall back
# to the documented key list when the engine is not installed.
try:
    from drafting.layout import SHEETS as _SHEETS
    SHEET_CHOICES = sorted(_SHEETS.keys())
except Exception:  # noqa: BLE001 -- engine optional at import time
    SHEET_CHOICES = ["ANSI_A", "ANSI_B", "ANSI_C", "ANSI_D",
                     "ANSI_E", "ARCH_C", "ARCH_D"]

try:
    from drafting.sadj import DraftRefused as _DraftRefused
except Exception:  # noqa: BLE001
    _DraftRefused = None


# ---------------------------------------------------------------------------
# small helpers (Tk-free where possible)
# ---------------------------------------------------------------------------

def parse_grid(text: str) -> list[list[float]]:
    """Parse ``"1,2;3,4"`` into [[1.0, 2.0], [3.0, 4.0]]."""
    rows = []
    for line in text.strip().split(";"):
        line = line.strip()
        if line:
            rows.append([float(x) for x in line.split(",")])
    if not rows or any(len(r) != len(rows[0]) for r in rows):
        raise ValueError("Grid must be rectangular, e.g. '1,2;3,4'")
    return rows


def _set_text(widget: tk.Text, text: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    widget.configure(state="disabled")


def _fmt_dict(d: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in d.items())


def _scrollable_text(parent, height: int = 12, width: int = 70) -> tk.Text:
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True, pady=4)
    text = tk.Text(frame, height=height, width=width, wrap="none",
                   state="disabled")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
    text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    text.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return text


# ---------------------------------------------------------------------------
# application
# ---------------------------------------------------------------------------

class SurveySuiteApp(tk.Tk):
    """The SurveySuite main window: six workflow tabs + status bar."""

    ARTIFACT_ROWS = [
        ("job_path", "Field job (.sfield.json)"),
        ("weights_path", "Weights (weights.json)"),
        ("sadj_path", "Adjustment (.sadj.json)"),
        ("report_path", "Justification report (.md)"),
        ("adjusted_job_path", "Adjusted job (.sfield.json)"),
        ("parcel_path", "Parcel (parcel.json)"),
        ("style_path", "Style (style.json)"),
        ("basemap_path", "Basemap (GeoTIFF)"),
    ]

    def __init__(self, license_status=None):
        super().__init__()
        self.title(f"SurveySuite {__version__}")
        self.geometry("1060x760")
        self.project: SurveyProject | None = None
        self.license_status = license_status
        self._update_msg = tk.StringVar(value="checking for updates...")

        self._build_menu()
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self._notebook = nb
        self._build_project_tab(nb)
        self._build_import_tab(nb)
        self._build_adjust_tab(nb)
        self._build_map_tab(nb)
        self._build_draft_tab(nb)
        self._build_basemap_tab(nb)

        self.status_var = tk.StringVar()
        status = ttk.Label(self, textvariable=self.status_var, anchor="w",
                           relief="sunken", padding=(6, 2))
        status.pack(fill="x", side="bottom")
        self._refresh_status()

        # update check never blocks the UI
        threading.Thread(target=self._check_updates, daemon=True).start()

    # -- menu / status -----------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project...",
                              command=self._new_project)
        file_menu.add_command(label="Open Project...",
                              command=self._open_project)
        file_menu.add_command(label="Save Project",
                              command=self._save_project)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.configure(menu=menubar)

    def _about(self):
        messagebox.showinfo(
            "About SurveySuite",
            f"SurveySuite {__version__}\n\n"
            "Field-to-finish desktop app for land surveying:\n"
            "Emlid field data -> weighted adjustment ->\n"
            "plat/plan/map PDFs with a sealed title block.\n\n"
            "Engines: survey-field, survey-adjust-workflow,\n"
            "survey-drafting, survey-basemap.")

    def _refresh_status(self):
        tier = self.license_status.tier if self.license_status else "unknown"
        self.status_var.set(
            f"v{__version__} | license: {tier} | {self._update_msg.get()}")

    def _check_updates(self):
        ok, latest = check_for_updates(__version__)
        def apply():
            if ok:
                self._update_msg.set(f"update available: {latest}")
            else:
                self._update_msg.set("up to date")
            self._refresh_status()
        self.after(0, apply)

    # -- worker-thread helper ----------------------------------------------
    def run_worker(self, work, on_done, on_error=None, busy=()):
        """Run ``work()`` (no Tk calls) in a daemon thread.

        ``on_done(result)`` / ``on_error(exc)`` are marshalled back onto
        the UI thread. Widgets in ``busy`` are disabled for the duration.
        """
        for w in busy:
            try:
                w.configure(state="disabled")
            except Exception:  # noqa: BLE001
                pass
        self.configure(cursor="watch")

        def target():
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 -- routed to on_error
                self.after(0, lambda e=exc: self._worker_done(
                    e, None, on_done, on_error, busy))
            else:
                self.after(0, lambda r=result: self._worker_done(
                    None, r, on_done, on_error, busy))

        threading.Thread(target=target, daemon=True).start()

    def _worker_done(self, exc, result, on_done, on_error, busy):
        self.configure(cursor="")
        for w in busy:
            try:
                w.configure(state="normal")
            except Exception:  # noqa: BLE001
                pass
        if exc is not None:
            if on_error is not None:
                on_error(exc)
            else:
                messagebox.showerror("Error", str(exc))
        else:
            on_done(result)

    # -- project helpers ----------------------------------------------------
    def _require_project(self) -> bool:
        if self.project is None:
            messagebox.showinfo("No project",
                                "Create or open a project first "
                                "(Project tab).")
            return False
        return True

    def set_project(self, proj: SurveyProject | None):
        self.project = proj
        if proj is not None:
            self.title(f"SurveySuite {__version__} -- {proj.name}")
            for attr, entry in (("surveyor_name", self.prof_name),
                                ("surveyor_license", self.prof_license),
                                ("surveyor_state", self.prof_state),
                                ("firm", self.prof_firm),
                                ("client", self.prof_client)):
                entry.delete(0, "end")
                entry.insert(0, getattr(proj, attr, "") or "")
            self._sync_draft_surveyor()
        else:
            self.title(f"SurveySuite {__version__}")
        self._refresh_checklist()
        self._refresh_recent()
        self.refresh_map()

    def _save_project(self):
        if not self._require_project():
            return
        p = self.project
        p.surveyor_name = self.prof_name.get().strip()
        p.surveyor_license = self.prof_license.get().strip()
        p.surveyor_state = self.prof_state.get().strip()
        p.firm = self.prof_firm.get().strip()
        p.client = self.prof_client.get().strip()
        path = p.save()
        self._refresh_checklist()
        self._refresh_recent()
        messagebox.showinfo("Project saved", f"Saved:\n{path}")

    def _new_project(self):
        name = self.proj_name.get().strip()
        directory = self.proj_dir.get().strip()
        crs = self.proj_crs.get().strip()
        if not name:
            messagebox.showerror("New project", "Enter a project name.")
            return
        if not directory:
            messagebox.showerror("New project", "Choose a project directory.")
            return
        try:
            proj = SurveyProject.new(name, directory, crs=crs)
            proj.save()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("New project", str(exc))
            return
        self.set_project(proj)

    def _open_project(self, path: str | None = None):
        if path is None:
            path = filedialog.askopenfilename(
                title="Open SurveySuite project",
                filetypes=[("SurveySuite project", "*.sproj"),
                           ("All files", "*.*")])
            if not path:
                return
        try:
            proj = SurveyProject.load(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open project", str(exc))
            return
        remember_project(os.path.abspath(path))
        self.set_project(proj)

    def _refresh_recent(self):
        self.recent_list.delete(0, "end")
        for path in recent_projects():
            self.recent_list.insert("end", path)

    def _refresh_checklist(self):
        lines = []
        if self.project is None:
            lines.append("No project open.")
        else:
            for attr, label in self.ARTIFACT_ROWS:
                mark = "✓" if self.project.artifact_exists(attr) else "✗"
                lines.append(f"{mark}  {label}")
            n = len(self.project.deliverables or [])
            lines.append(f"{'✓' if n else '✗'}  Deliverables ({n} PDF manifests)")
        _set_text(self.checklist_text, "\n".join(lines))

    # =====================================================================
    # tab 1: Project
    # =====================================================================
    def _build_project_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="Project")

        top = ttk.LabelFrame(frame, text="Project file", padding=8)
        top.pack(fill="x")
        for col in (1,):
            top.columnconfigure(col, weight=1)
        ttk.Label(top, text="Name:").grid(row=0, column=0, sticky="w")
        self.proj_name = ttk.Entry(top)
        self.proj_name.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(top, text="Directory:").grid(row=1, column=0, sticky="w")
        dirrow = ttk.Frame(top)
        dirrow.grid(row=1, column=1, sticky="ew", padx=4)
        dirrow.columnconfigure(0, weight=1)
        self.proj_dir = ttk.Entry(dirrow)
        self.proj_dir.grid(row=0, column=0, sticky="ew")
        ttk.Button(dirrow, text="Browse...",
                   command=self._browse_project_dir).grid(row=0, column=1,
                                                          padx=(4, 0))
        ttk.Label(top, text="CRS:").grid(row=2, column=0, sticky="w")
        self.proj_crs = ttk.Entry(top)
        self.proj_crs.grid(row=2, column=1, sticky="ew", padx=4)
        btnrow = ttk.Frame(top)
        btnrow.grid(row=3, column=0, columnspan=2, pady=(6, 0))
        ttk.Button(btnrow, text="New project",
                   command=self._new_project).pack(side="left", padx=4)
        ttk.Button(btnrow, text="Open...",
                   command=self._open_project).pack(side="left", padx=4)
        ttk.Button(btnrow, text="Save project",
                   command=self._save_project).pack(side="left", padx=4)

        recent = ttk.LabelFrame(frame, text="Recent projects", padding=8)
        recent.pack(fill="both", expand=True, pady=(8, 0))
        self.recent_list = tk.Listbox(recent, height=5)
        self.recent_list.pack(fill="both", expand=True)
        self.recent_list.bind("<Double-Button-1>",
                              lambda e: self._open_recent_selected())
        ttk.Button(recent, text="Open selected",
                   command=self._open_recent_selected).pack(pady=(4, 0))
        self._refresh_recent()

        prof = ttk.LabelFrame(frame, text="Surveyor profile", padding=8)
        prof.pack(fill="x", pady=(8, 0))
        prof.columnconfigure(1, weight=1)
        prof.columnconfigure(3, weight=1)
        self.prof_name = self._labeled_entry(prof, "Name:", 0, 0)
        self.prof_license = self._labeled_entry(prof, "License #:", 0, 2)
        self.prof_state = self._labeled_entry(prof, "State:", 1, 0)
        self.prof_firm = self._labeled_entry(prof, "Firm:", 1, 2)
        self.prof_client = self._labeled_entry(prof, "Client:", 2, 0)

        chk = ttk.LabelFrame(frame, text="Artifacts", padding=8)
        chk.pack(fill="both", expand=True, pady=(8, 0))
        self.checklist_text = tk.Text(chk, height=10, width=60,
                                      state="disabled")
        self.checklist_text.pack(fill="both", expand=True)
        ttk.Button(chk, text="Refresh",
                   command=self._refresh_checklist).pack(pady=(4, 0))
        self._refresh_checklist()

    def _labeled_entry(self, parent, label, row, col):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w",
                                           padx=(0, 4), pady=2)
        entry = ttk.Entry(parent)
        entry.grid(row=row, column=col + 1, sticky="ew", padx=(0, 12), pady=2)
        return entry

    def _browse_project_dir(self):
        d = filedialog.askdirectory(title="Project directory")
        if d:
            self.proj_dir.delete(0, "end")
            self.proj_dir.insert(0, d)

    def _open_recent_selected(self):
        sel = self.recent_list.curselection()
        if sel:
            self._open_project(self.recent_list.get(sel[0]))

    # =====================================================================
    # tab 2: Import
    # =====================================================================
    def _build_import_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="Import")
        self.import_csvs: list[str] = []
        self.last_import = None  # (ImportResult, tmp job path)

        files = ttk.LabelFrame(frame, text="Emlid CSV files", padding=8)
        files.pack(fill="x")
        self.import_list = tk.Listbox(files, height=4)
        self.import_list.pack(fill="x")
        fbtn = ttk.Frame(files)
        fbtn.pack(pady=(4, 0))
        ttk.Button(fbtn, text="Add CSVs...",
                   command=self._import_add_csvs).pack(side="left", padx=4)
        ttk.Button(fbtn, text="Remove selected",
                   command=self._import_remove_csv).pack(side="left", padx=4)

        thr = ttk.LabelFrame(frame, text="Validation thresholds", padding=8)
        thr.pack(fill="x", pady=(8, 0))
        thr.columnconfigure(1, weight=1)
        thr.columnconfigure(3, weight=1)
        self.thr_rms_lat = self._labeled_entry(thr, "RMS lateral (m):", 0, 0)
        self.thr_rms_lat.insert(0, "0.02")
        self.thr_rms_el = self._labeled_entry(thr, "RMS elev (m):", 0, 2)
        self.thr_rms_el.insert(0, "0.03")
        self.thr_pdop = self._labeled_entry(thr, "PDOP:", 1, 0)
        self.thr_pdop.insert(0, "3.0")
        self.thr_base = self._labeled_entry(thr, "Baseline (km):", 1, 2)
        self.thr_base.insert(0, "10.0")

        act = ttk.Frame(frame)
        act.pack(pady=8)
        self.import_run_btn = ttk.Button(act, text="Run import",
                                         command=self._run_import)
        self.import_run_btn.pack(side="left", padx=4)
        self.import_save_btn = ttk.Button(act, text="Save job into project",
                                          command=self._save_import_job)
        self.import_save_btn.pack(side="left", padx=4)

        ttk.Label(frame, text="Validation report:").pack(anchor="w")
        self.import_report = _scrollable_text(frame, height=16)

    def _import_add_csvs(self):
        paths = filedialog.askopenfilenames(
            title="Select Emlid CSV files",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        for p in paths:
            if p not in self.import_csvs:
                self.import_csvs.append(p)
                self.import_list.insert("end", p)

    def _import_remove_csv(self):
        for idx in reversed(self.import_list.curselection()):
            self.import_list.delete(idx)
            del self.import_csvs[idx]

    def _read_thresholds(self) -> dict:
        try:
            return {
                "rms_lateral": float(self.thr_rms_lat.get()),
                "rms_elev": float(self.thr_rms_el.get()),
                "pdop": float(self.thr_pdop.get()),
                "baseline_km": float(self.thr_base.get()),
            }
        except ValueError:
            raise ValueError("thresholds must be numbers")

    def _run_import(self):
        if not self.import_csvs:
            messagebox.showerror("Import", "Add at least one CSV file.")
            return
        try:
            thresholds = self._read_thresholds()
        except ValueError as exc:
            messagebox.showerror("Import", str(exc))
            return

        def work():
            tmp = tempfile.NamedTemporaryFile(suffix=".sfield.json",
                                              delete=False)
            tmp.close()
            result = runners.run_import(
                list(self.import_csvs), tmp.name,
                project_name=(self.project.name
                              if self.project else ""),
                thresholds=thresholds)
            return result, tmp.name

        def done(res):
            result, tmp_path = res
            self.last_import = (result, tmp_path)
            _set_text(self.import_report,
                      self._format_import_report(result))
            if not result.ok:
                messagebox.showwarning(
                    "Import finished with errors",
                    f"{result.n_errors} error(s), "
                    f"{result.n_warnings} warning(s). "
                    "Fix the CSVs and re-run before adjusting.")

        self.run_worker(work, done, busy=[self.import_run_btn])

    @staticmethod
    def _format_import_report(result) -> str:
        lines = ["Import summary:"]
        for k, v in result.summary.items():
            lines.append(f"  {k}: {v}")
        lines += ["",
                  f"===== ERRORS ({result.n_errors}) ====="]
        for i in result.issues:
            if i["severity"] == "error":
                lines.append(f"  [{i['code']}] {i['message']}"
                             + (f"  (point: {i['point_name']})"
                                if i.get("point_name") else ""))
        lines += ["",
                  f"===== WARNINGS ({result.n_warnings}) ====="]
        for i in result.issues:
            if i["severity"] == "warning":
                lines.append(f"  [{i['code']}] {i['message']}"
                             + (f"  (point: {i['point_name']})"
                                if i.get("point_name") else ""))
        if result.n_errors == 0 and result.n_warnings == 0:
            lines.append("  (none)")
        return "\n".join(lines)

    def _save_import_job(self):
        if not self._require_project():
            return
        if not self.last_import:
            messagebox.showerror("Save job", "Run the import first.")
            return
        _result, tmp_path = self.last_import
        dest = os.path.join(self.project.root,
                            f"{self.project.name}.sfield.json")
        try:
            shutil.copyfile(tmp_path, dest)
            self.project.set_artifact("job_path", dest)
            self.project.save()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save job", str(exc))
            return
        self._refresh_checklist()
        self.refresh_map()
        messagebox.showinfo("Job saved", f"Job written to:\n{dest}")

    # =====================================================================
    # tab 3: Adjust
    # =====================================================================
    WEIGHT_FIELDS = [
        ("rtk", "rms_scale", "RTK RMS scale"),
        ("rtk", "min_sigma_m", "RTK min sigma (m)"),
        ("rtk", "default_sigma_m", "RTK default sigma (m)"),
        ("rtk", "downweight_factor", "RTK downweight factor"),
        ("levels", "mm_per_sqrt_km", "Levels mm per sqrt(km)"),
        ("levels", "min_sigma_m", "Levels min sigma (m)"),
        ("angles", "arcseconds", "Angles sigma (arcsec)"),
        ("distances", "mm", "Distances constant (mm)"),
        ("distances", "ppm", "Distances ppm"),
    ]

    def _build_adjust_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="Adjust")

        wbox = ttk.LabelFrame(frame, text="Stochastic model (weights)",
                              padding=8)
        wbox.pack(fill="x")
        wbox.columnconfigure(1, weight=1)
        wbox.columnconfigure(3, weight=1)
        self.w_entries = {}
        for i, (section, key, label) in enumerate(self.WEIGHT_FIELDS):
            row, col = divmod(i, 2)
            ttk.Label(wbox, text=label + ":").grid(
                row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
            entry = ttk.Entry(wbox, width=14)
            entry.grid(row=row, column=col * 2 + 1, sticky="w", pady=2)
            self.w_entries[(section, key)] = entry
        prow = (len(self.WEIGHT_FIELDS) + 1) // 2
        ttk.Label(wbox, text="RTK FLOAT/SINGLE policy:").grid(
            row=prow, column=0, sticky="w", padx=(0, 4), pady=2)
        self.w_float_policy = ttk.Combobox(
            wbox, values=["exclude", "downweight", "include"],
            state="readonly", width=12)
        self.w_float_policy.set("exclude")
        self.w_float_policy.grid(row=prow, column=1, sticky="w", pady=2)
        ttk.Label(wbox, text="Datum hold (stations, comma-sep; empty=all bases):").grid(
            row=prow + 1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.w_datum_hold = ttk.Entry(wbox)
        self.w_datum_hold.grid(row=prow + 2, column=0, columnspan=4,
                               sticky="ew", pady=2)
        ttk.Label(wbox, text="Overrides (JSON list):").grid(
            row=prow + 3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.w_overrides = tk.Text(wbox, height=4, width=60)
        self.w_overrides.grid(row=prow + 4, column=0, columnspan=4,
                              sticky="ew", pady=2)

        wbtn = ttk.Frame(frame)
        wbtn.pack(pady=6)
        ttk.Button(wbtn, text="Load defaults",
                   command=self._weights_load_defaults).pack(side="left",
                                                             padx=4)
        ttk.Button(wbtn, text="Validate",
                   command=self._weights_validate).pack(side="left", padx=4)
        ttk.Button(wbtn, text="Save weights.json",
                   command=self._weights_save).pack(side="left", padx=4)
        ttk.Label(frame, text="Weights validation:").pack(anchor="w")
        self.weights_out = _scrollable_text(frame, height=5)

        runbox = ttk.LabelFrame(frame, text="Run adjustment", padding=8)
        runbox.pack(fill="x", pady=(6, 0))
        self.adj_rtk = tk.BooleanVar(value=True)
        self.adj_levels = tk.BooleanVar(value=True)
        self.adj_trav = tk.BooleanVar(value=False)
        ttk.Checkbutton(runbox, text="RTK",
                        variable=self.adj_rtk).pack(side="left", padx=4)
        ttk.Checkbutton(runbox, text="Levels",
                        variable=self.adj_levels).pack(side="left", padx=4)
        ttk.Checkbutton(runbox, text="Traverse",
                        variable=self.adj_trav).pack(side="left", padx=4)
        ttk.Label(runbox, text="Traverse file:").pack(side="left", padx=(8, 2))
        self.adj_trav_path = ttk.Entry(runbox, width=28)
        self.adj_trav_path.pack(side="left")
        ttk.Button(runbox, text="...",
                   command=self._browse_traverse).pack(side="left", padx=2)
        self.adj_run_btn = ttk.Button(runbox, text="Run adjustment",
                                      command=self._run_adjustment)
        self.adj_run_btn.pack(side="left", padx=8)

        self.verdict_banner = tk.Label(frame, text="", font=(
            "TkDefaultFont", 12, "bold"), anchor="w", padx=8, pady=4)
        self.verdict_banner.pack(fill="x", pady=(6, 0))

        ttk.Label(frame, text="Justification report:").pack(anchor="w")
        self.adjust_report = _scrollable_text(frame, height=14)
        ttk.Label(frame, text="Notes:").pack(anchor="w")
        self.adjust_notes = tk.Listbox(frame, height=4)
        self.adjust_notes.pack(fill="x")

        self._weights_load_defaults(silent=True)

    def _browse_traverse(self):
        p = filedialog.askopenfilename(
            title="Traverse observation file",
            filetypes=[("All files", "*.*")])
        if p:
            self.adj_trav_path.delete(0, "end")
            self.adj_trav_path.insert(0, p)

    def _weights_load_defaults(self, silent=False):
        try:
            cfg = runners.default_weights()
        except Exception as exc:  # noqa: BLE001
            if not silent:
                messagebox.showerror("Weights", f"Could not load defaults: "
                                     f"{exc}")
            return
        for (section, key), entry in self.w_entries.items():
            entry.delete(0, "end")
            entry.insert(0, str(cfg.get(section, {}).get(key, "")))
        self.w_float_policy.set(
            str(cfg.get("rtk", {}).get("float_policy", "exclude")))
        hold = cfg.get("datum_hold") or []
        self.w_datum_hold.delete(0, "end")
        self.w_datum_hold.insert(0, ", ".join(str(s) for s in hold))
        self.w_overrides.delete("1.0", "end")
        self.w_overrides.insert("1.0",
                                json.dumps(cfg.get("overrides", []), indent=2))

    def _collect_weights(self) -> dict:
        cfg: dict = {"rtk": {}, "levels": {}, "angles": {},
                     "distances": {}}
        for (section, key), entry in self.w_entries.items():
            text = entry.get().strip()
            if not text:
                raise ValueError(f"weights field {section}.{key} is empty")
            try:
                cfg[section][key] = float(text)
            except ValueError:
                raise ValueError(f"weights field {section}.{key} must be "
                                 f"a number (got {text!r})")
        cfg["rtk"]["float_policy"] = self.w_float_policy.get()
        hold = self.w_datum_hold.get().strip()
        cfg["datum_hold"] = [s.strip() for s in hold.split(",") if s.strip()]
        raw = self.w_overrides.get("1.0", "end").strip()
        if raw:
            try:
                ov = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"overrides JSON: {exc}")
            if not isinstance(ov, list):
                raise ValueError("overrides must be a JSON list")
            cfg["overrides"] = ov
        else:
            cfg["overrides"] = []
        return cfg

    def _weights_validate(self):
        try:
            cfg = self._collect_weights()
        except ValueError as exc:
            _set_text(self.weights_out, f"INVALID:\n  - {exc}")
            return
        problems = runners.validate_weights(cfg)
        if problems:
            _set_text(self.weights_out,
                      "INVALID:\n" + "\n".join(f"  - {p}"
                                              for p in problems))
        else:
            _set_text(self.weights_out,
                      "Weights configuration is valid.\n\n"
                      + runners.weights_summary(cfg))

    def _weights_save(self):
        if not self._require_project():
            return
        try:
            cfg = self._collect_weights()
        except ValueError as exc:
            messagebox.showerror("Weights", str(exc))
            return
        problems = runners.validate_weights(cfg)
        if problems:
            messagebox.showerror("Weights invalid", "\n".join(problems))
            return
        dest = os.path.join(self.project.root, "weights.json")
        try:
            with open(dest, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
            self.project.set_artifact("weights_path", dest)
            self.project.save()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save weights", str(exc))
            return
        self._refresh_checklist()
        messagebox.showinfo("Weights saved", f"Saved:\n{dest}")

    def _run_adjustment(self):
        if not self._require_project():
            return
        if not self.project.artifact_exists("job_path"):
            messagebox.showerror("Adjustment",
                                 "No field job in the project -- "
                                 "run Import first.")
            return
        try:
            cfg = self._collect_weights()
        except ValueError as exc:
            messagebox.showerror("Weights", str(exc))
            return
        problems = runners.validate_weights(cfg)
        if problems:
            messagebox.showerror("Weights invalid", "\n".join(problems))
            return
        paths = tuple(p for p, var in (("rtk", self.adj_rtk),
                                        ("levels", self.adj_levels),
                                        ("traverse", self.adj_trav))
                      if var.get())
        if not paths:
            messagebox.showerror("Adjustment",
                                 "Select at least one adjustment path.")
            return
        trav_path = self.adj_trav_path.get().strip() or None
        if "traverse" in paths and not trav_path:
            messagebox.showerror("Adjustment",
                                 "Traverse path selected but no traverse "
                                 "file given.")
            return
        job_path = self.project.resolve(self.project.job_path)
        out_dir = self.project.root

        def work():
            return runners.run_adjust(job_path, cfg, out_dir,
                                      name="adjustment", paths=paths,
                                      traverse_path=trav_path)

        self.run_worker(work, self._adjust_done, busy=[self.adj_run_btn])

    def _adjust_done(self, result):
        if result.valid:
            self.verdict_banner.configure(text="VALID", bg="#1a9e4b",
                                          fg="white")
        else:
            self.verdict_banner.configure(text="NOT VALID", bg="#d23b3b",
                                          fg="white")
        lines = ["Validity checks:"]
        for c in result.checks:
            mark = "PASS" if c["ok"] else "FAIL"
            lines.append(f"  [{mark}] {c['criterion']}: {c['detail']}")
        lines += ["", f"Points: {result.n_points}", ""]
        try:
            lines.append(runners.read_report(result.report_path))
        except Exception as exc:  # noqa: BLE001
            lines.append(f"(could not read report: {exc})")
        _set_text(self.adjust_report, "\n".join(lines))
        self.adjust_notes.delete(0, "end")
        for note in result.notes:
            self.adjust_notes.insert("end", note)
        p = self.project
        p.set_artifact("sadj_path", result.sadj_path)
        p.set_artifact("report_path", result.report_path)
        p.set_artifact("adjusted_job_path", result.adjusted_job_path)
        p.save()
        self._refresh_checklist()
        self.refresh_map()
        if not result.valid:
            messagebox.showwarning(
                "Adjustment NOT VALID",
                "The adjustment failed its validity checks.\n"
                "Drafting is refused until the data passes -- "
                "see the justification report.")

    # =====================================================================
    # tab 4: Map
    # =====================================================================
    def _build_map_tab(self, nb):
        frame = ttk.Frame(nb, padding=6)
        nb.add(frame, text="Map")

        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(toolbar, text="Fit",
                   command=self._map_fit).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Refresh",
                   command=self.refresh_map).pack(side="left", padx=2)
        self.map_basemap_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="Basemap",
                        variable=self.map_basemap_var,
                        command=self.refresh_map).pack(side="left", padx=8)
        ttk.Label(toolbar, text="Opacity:").pack(side="left")
        self.map_opacity = tk.Scale(toolbar, from_=0.2, to=1.0,
                                    resolution=0.05, orient="horizontal",
                                    length=110)
        self.map_opacity.set(0.8)
        self.map_opacity.pack(side="left", padx=2)
        self.map_status = tk.StringVar(value="No data")
        ttk.Label(toolbar, textvariable=self.map_status,
                  foreground="#555555").pack(side="right", padx=4)

        self.mapview = SurveyMapView(frame)
        self.mapview.pack(fill="both", expand=True)

    def _map_fit(self):
        self.mapview.fit()
        self.mapview._redraw()

    def _parcel_point_order(self) -> list[str]:
        """Boundary point order from the project's parcel.json, if any."""
        if self.project is None or not self.project.artifact_exists(
                "parcel_path"):
            return []
        try:
            with open(self.project.resolve(self.project.parcel_path),
                       encoding="utf-8") as fh:
                parcel = json.load(fh)
            segs = parcel.get("segments") or []
            if not segs:
                return []
            return [segs[0]["from"]] + [s["to"] for s in segs]
        except Exception:  # noqa: BLE001 -- parcel is optional garnish
            return []

    def refresh_map(self):
        """Reload points (and basemap) from the project artifacts."""
        if not hasattr(self, "mapview"):
            return
        proj = self.project
        if proj is None or not (proj.artifact_exists("job_path")
                                or proj.artifact_exists("sadj_path")):
            self.mapview.set_data([])
            self.mapview.clear_basemap()
            self.map_status.set("No data -- import a job to begin.")
            return
        job = (proj.resolve(proj.job_path)
               if proj.artifact_exists("job_path") else None)
        sadj = (proj.resolve(proj.sadj_path)
                if proj.artifact_exists("sadj_path") else None)
        try:
            points = runners.map_points(job_path=job, sadj_path=sadj)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Map", f"Could not load points: {exc}")
            return
        extent = runners.map_extent(points)
        self.mapview.set_data(points, extent=extent,
                              parcel_names=self._parcel_point_order(),
                              units="m")
        self.map_status.set(f"{len(points)} point(s)")
        if self.map_basemap_var.get() and proj.artifact_exists("basemap_path"):
            self._render_basemap_async(proj)
        else:
            self.mapview.clear_basemap()

    def _render_basemap_async(self, proj):
        tif = proj.resolve(proj.basemap_path)
        opacity = float(self.map_opacity.get())
        crs = proj.crs or None

        def work():
            with runners.make_basemap_source(
                    tif, project_crs=crs, opacity=opacity) as src:
                data, w, h, _mode = src.image()
                extent = src.extent_world()
            return data, w, h, extent

        def done(res):
            data, w, h, extent = res
            try:
                photo = photoimage_from_rgb(data, w, h)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Basemap",
                                     f"Could not render basemap: {exc}")
                return
            self.mapview.set_basemap_image(photo, extent)

        def err(exc):
            messagebox.showerror("Basemap", f"Could not load basemap: {exc}")
            self.map_basemap_var.set(False)

        self.run_worker(work, done, on_error=err)

    # =====================================================================
    # tab 5: Draft
    # =====================================================================
    FT_SCALES = ["fit", "10", "20", "30", "40", "50", "60", "100"]
    M_SCALES = ["fit", "250", "500", "1000", "2000", "5000"]
    HIDE_LAYERS = ["basemap", "easements", "boundary", "linework", "points",
                   "control", "annotations"]

    def _build_draft_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="Draft")
        self.draft_parcel: dict | None = None

        # -- parcel builder ------------------------------------------------
        pbox = ttk.LabelFrame(frame, text="Parcel boundary", padding=8)
        pbox.pack(fill="x")
        cols = ttk.Frame(pbox)
        cols.pack(fill="x")
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(2, weight=1)
        ttk.Label(cols, text="Adjusted points:").grid(row=0, column=0,
                                                      sticky="w")
        ttk.Label(cols, text="Parcel order:").grid(row=0, column=2,
                                                   sticky="w")
        self.draft_available = tk.Listbox(cols, height=6, selectmode="extended")
        self.draft_available.grid(row=1, column=0, sticky="nsew")
        mid = ttk.Frame(cols)
        mid.grid(row=1, column=1, padx=6)
        ttk.Button(mid, text="Add →",
                   command=self._draft_add).pack(pady=2)
        ttk.Button(mid, text="← Remove",
                   command=self._draft_remove).pack(pady=2)
        ttk.Button(mid, text="Up",
                   command=lambda: self._draft_move(-1)).pack(pady=2)
        ttk.Button(mid, text="Down",
                   command=lambda: self._draft_move(1)).pack(pady=2)
        self.draft_selected = tk.Listbox(cols, height=6, selectmode="extended")
        self.draft_selected.grid(row=1, column=2, sticky="nsew")
        prow = ttk.Frame(pbox)
        prow.pack(fill="x", pady=(6, 0))
        ttk.Button(prow, text="Load adjusted points",
                   command=self._draft_load_points).pack(side="left", padx=2)
        ttk.Label(prow, text="Units:").pack(side="left", padx=(8, 2))
        self.draft_units = ttk.Combobox(prow, values=["ft", "m"],
                                        state="readonly", width=5)
        self.draft_units.set("ft")
        self.draft_units.pack(side="left")
        self.draft_units.bind("<<ComboboxSelected>>",
                              lambda e: self._draft_units_changed())
        ttk.Button(prow, text="Build parcel",
                   command=self._draft_build_parcel).pack(side="left",
                                                          padx=8)
        self.draft_parcel_label = ttk.Label(prow, text="No parcel built.",
                                            foreground="#555555")
        self.draft_parcel_label.pack(side="left", padx=4)

        # -- compose options -----------------------------------------------
        obox = ttk.LabelFrame(frame, text="Compose options", padding=8)
        obox.pack(fill="x", pady=(8, 0))
        obox.columnconfigure(1, weight=1)
        obox.columnconfigure(3, weight=1)
        r = 0
        self.draft_title = self._labeled_entry(obox, "Title:", r, 0)
        self.draft_sheet = self._labeled_combo(obox, "Sheet:", r, 2,
                                               SHEET_CHOICES, "ANSI_C")
        r += 1
        self.draft_location = self._labeled_entry(obox, "Location:", r, 0)
        self.draft_scale = self._labeled_combo(obox, "Scale:", r, 2,
                                               self.FT_SCALES, "fit")
        r += 1
        self.draft_client = self._labeled_entry(obox, "Client:", r, 0)
        self.draft_kind = self._labeled_combo(obox, "Kind:", r, 2,
                                              ["plat", "plan", "map"],
                                              "plat")
        r += 1
        self.draft_firm = self._labeled_entry(obox, "Firm:", r, 0)
        self.draft_sheet_no = self._labeled_entry(obox, "Sheet no.:", r, 2)
        self.draft_sheet_no.insert(0, "1")
        r += 1
        self.draft_project_no = self._labeled_entry(obox, "Project no.:",
                                                    r, 0)
        self.draft_sheet_count = self._labeled_entry(obox, "Of sheets:", r, 2)
        self.draft_sheet_count.insert(0, "1")
        r += 1
        self.draft_date = self._labeled_entry(obox, "Date:", r, 0)
        self.draft_date.insert(0, datetime.date.today().isoformat())
        self.draft_bearings = self._labeled_entry(obox, "Basis of bearings:",
                                                  r, 2)
        r += 1
        self.draft_datum = self._labeled_entry(obox, "Datum note:", r, 0)
        self.draft_datum.grid_configure(columnspan=3, sticky="ew")

        sbox = ttk.LabelFrame(frame, text="Surveyor (seal block)",
                              padding=8)
        sbox.pack(fill="x", pady=(8, 0))
        sbox.columnconfigure(1, weight=1)
        sbox.columnconfigure(3, weight=1)
        self.draft_surv_name = self._labeled_entry(sbox, "Name:", 0, 0)
        self.draft_surv_lic = self._labeled_entry(sbox, "License #:", 0, 2)
        self.draft_surv_state = self._labeled_entry(sbox, "State:", 1, 0)
        ttk.Button(sbox, text="Prefill from Project",
                   command=self._sync_draft_surveyor).grid(row=1, column=2,
                                                           columnspan=2,
                                                           sticky="e")

        hbox = ttk.LabelFrame(frame, text="Hidden layers", padding=8)
        hbox.pack(fill="x", pady=(8, 0))
        self.draft_hide = {}
        for name in self.HIDE_LAYERS:
            var = tk.BooleanVar(value=False)
            self.draft_hide[name] = var
            ttk.Checkbutton(hbox, text=name, variable=var).pack(side="left",
                                                               padx=4)
        self.draft_use_basemap = tk.BooleanVar(value=False)
        ttk.Checkbutton(hbox, text="Include basemap",
                        variable=self.draft_use_basemap).pack(side="left",
                                                              padx=(12, 2))
        ttk.Label(hbox, text="opacity:").pack(side="left")
        self.draft_basemap_opacity = ttk.Entry(hbox, width=5)
        self.draft_basemap_opacity.insert(0, "0.8")
        self.draft_basemap_opacity.pack(side="left")

        stbox = ttk.LabelFrame(frame, text="Style (JSON)", padding=8)
        stbox.pack(fill="x", pady=(8, 0))
        self.draft_style = tk.Text(stbox, height=5, width=70)
        self.draft_style.pack(fill="x")
        sbtn = ttk.Frame(stbox)
        sbtn.pack(pady=(4, 0))
        ttk.Button(sbtn, text="Load template",
                   command=self._draft_load_style).pack(side="left", padx=4)
        ttk.Button(sbtn, text="Validate style",
                   command=self._draft_validate_style).pack(side="left",
                                                            padx=4)

        act = ttk.Frame(frame)
        act.pack(pady=8)
        self.draft_compose_btn = ttk.Button(act, text="Compose PDF",
                                            command=self._draft_compose)
        self.draft_compose_btn.pack()

        ttk.Label(frame, text="Manifest:").pack(anchor="w")
        self.draft_out = _scrollable_text(frame, height=10)

    def _labeled_combo(self, parent, label, row, col, values, default):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w",
                                           padx=(0, 4), pady=2)
        combo = ttk.Combobox(parent, values=list(values), state="readonly",
                             width=14)
        combo.set(default)
        combo.grid(row=row, column=col + 1, sticky="w", pady=2)
        return combo

    def _draft_units_changed(self):
        self.draft_scale.configure(
            values=self.FT_SCALES if self.draft_units.get() == "ft"
            else self.M_SCALES)
        self.draft_scale.set("fit")

    def _sync_draft_surveyor(self):
        p = self.project
        if p is None:
            return
        for entry, val in ((self.draft_surv_name, p.surveyor_name),
                           (self.draft_surv_lic, p.surveyor_license),
                           (self.draft_surv_state, p.surveyor_state)):
            entry.delete(0, "end")
            entry.insert(0, val or "")
        if not self.draft_firm.get().strip() and p.firm:
            self.draft_firm.delete(0, "end")
            self.draft_firm.insert(0, p.firm)
        if not self.draft_client.get().strip() and p.client:
            self.draft_client.delete(0, "end")
            self.draft_client.insert(0, p.client)

    def _draft_load_points(self):
        if not self._require_project():
            return
        if not self.project.artifact_exists("sadj_path"):
            messagebox.showerror("Draft",
                                 "No adjustment in the project -- "
                                 "run Adjust first.")
            return
        try:
            pts = runners.map_points(
                sadj_path=self.project.resolve(self.project.sadj_path))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Draft", f"Could not read points: {exc}")
            return
        self.draft_available.delete(0, "end")
        for p in pts:
            self.draft_available.insert("end", p["name"])
        # drop points already in the parcel order
        selected = set(self.draft_selected.get(0, "end"))
        for i in reversed(range(self.draft_available.size())):
            if self.draft_available.get(i) in selected:
                self.draft_available.delete(i)

    def _draft_add(self):
        for idx in self.draft_available.curselection():
            name = self.draft_available.get(idx)
            self.draft_selected.insert("end", name)
        for idx in reversed(self.draft_available.curselection()):
            self.draft_available.delete(idx)

    def _draft_remove(self):
        for idx in reversed(self.draft_selected.curselection()):
            name = self.draft_selected.get(idx)
            self.draft_selected.delete(idx)
            self.draft_available.insert("end", name)

    def _draft_move(self, direction):
        sel = list(self.draft_selected.curselection())
        if not sel:
            return
        items = list(self.draft_selected.get(0, "end"))
        for idx in (sel if direction < 0 else reversed(sel)):
            j = idx + direction
            if 0 <= j < len(items):
                items[idx], items[j] = items[j], items[idx]
        self.draft_selected.delete(0, "end")
        for name in items:
            self.draft_selected.insert("end", name)

    def _draft_build_parcel(self):
        names = list(self.draft_selected.get(0, "end"))
        if len(names) < 3:
            messagebox.showerror("Parcel",
                                 "Select at least 3 points for a parcel.")
            return
        units = self.draft_units.get()
        try:
            self.draft_parcel = runners.parcel_template(names, units=units)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Parcel", str(exc))
            return
        self.draft_parcel_label.configure(
            text=f"Parcel: {len(names)} points · units {units}")

    def _draft_load_style(self):
        try:
            tmpl = runners.style_template()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Style", str(exc))
            return
        self.draft_style.delete("1.0", "end")
        self.draft_style.insert("1.0", json.dumps(tmpl, indent=2))

    def _draft_validate_style(self):
        raw = self.draft_style.get("1.0", "end").strip()
        if not raw:
            messagebox.showinfo("Style", "Style is empty -- the default "
                               "style will be used.")
            return
        try:
            style = json.loads(raw)
        except json.JSONDecodeError as exc:
            messagebox.showerror("Style", f"Invalid JSON: {exc}")
            return
        problems = runners.validate_style(style)
        if problems:
            messagebox.showerror("Style invalid", "\n".join(problems))
        else:
            messagebox.showinfo("Style", "Style is valid.")

    def _draft_compose(self):
        if not self._require_project():
            return
        if not self.project.artifact_exists("sadj_path"):
            messagebox.showerror("Compose",
                                 "No adjustment in the project -- "
                                 "run Adjust first.")
            return
        if self.draft_parcel is None:
            messagebox.showerror("Compose", "Build a parcel first.")
            return
        style_text = self.draft_style.get("1.0", "end").strip()
        try:
            style = json.loads(style_text) if style_text else None
        except json.JSONDecodeError as exc:
            messagebox.showerror("Compose", f"Style JSON invalid: {exc}")
            return
        try:
            sheet_no = int(self.draft_sheet_no.get().strip() or "1")
            sheet_count = int(self.draft_sheet_count.get().strip() or "1")
        except ValueError:
            messagebox.showerror("Compose",
                                 "Sheet no. / of sheets must be integers.")
            return
        try:
            opacity = float(self.draft_basemap_opacity.get().strip() or "0.8")
        except ValueError:
            messagebox.showerror("Compose", "Basemap opacity must be a "
                                 "number 0.2-1.0.")
            return

        parcel = self.draft_parcel
        sadj_path = self.project.resolve(self.project.sadj_path)
        kind = self.draft_kind.get()
        options = {
            "kind": kind,
            "sheet": self.draft_sheet.get(),
            "scale": self.draft_scale.get(),
            "title": self.draft_title.get().strip(),
            "location": self.draft_location.get().strip(),
            "client": self.draft_client.get().strip(),
            "firm": self.draft_firm.get().strip(),
            "project_no": self.draft_project_no.get().strip(),
            "date": self.draft_date.get().strip(),
            "surveyor": {
                "name": self.draft_surv_name.get().strip(),
                "license_no": self.draft_surv_lic.get().strip(),
                "state": self.draft_surv_state.get().strip(),
            },
            "basis_of_bearings": self.draft_bearings.get().strip(),
            "datum_note": self.draft_datum.get().strip(),
            "hide": [n for n, v in self.draft_hide.items() if v.get()],
            "sheet_no": sheet_no,
            "sheet_count": sheet_count,
        }
        out_pdf = os.path.join(self.project.root,
                               f"{self.project.name}_{kind}.pdf")
        use_bm = (self.draft_use_basemap.get()
                  and self.project.artifact_exists("basemap_path"))
        tif = self.project.resolve(
            self.project.basemap_path) if use_bm else None
        crs = self.project.crs or None

        def work():
            src = None
            if tif:
                src = runners.make_basemap_source(
                    tif, project_crs=crs, opacity=opacity)
                src.__enter__()
            try:
                manifest = runners.run_draft(
                    sadj_path, parcel, style, out_pdf, options=options,
                    basemap_source=src)
            finally:
                if src is not None:
                    src.__exit__(None, None, None)
            return manifest, out_pdf

        def done(res):
            manifest, pdf = res
            _set_text(self.draft_out,
                      f"PDF: {pdf}\n\n" + json.dumps(manifest, indent=2))
            self.project.deliverables.append(manifest)
            self.project.save()
            self._refresh_checklist()
            messagebox.showinfo("Compose finished", f"PDF written to:\n{pdf}")

        def err(exc):
            if _DraftRefused is not None and isinstance(exc, _DraftRefused):
                lines = [f"  - {name}: {detail}"
                         for name, detail in exc.failed]
                _set_text(self.draft_out,
                          "DRAFT REFUSED -- the adjustment is NOT VALID. "
                          "There is no override.\n\nFailed criteria:\n"
                          + "\n".join(lines))
                self.draft_out.tag_add("err", "1.0", "end")
                self.draft_out.tag_config("err", foreground="#d23b3b")
            else:
                messagebox.showerror("Compose PDF", str(exc))

        self.run_worker(work, done, on_error=err,
                        busy=[self.draft_compose_btn])

    # =====================================================================
    # tab 6: Basemap
    # =====================================================================
    GSD_SCALES = ["1:10", "1:20", "1:30", "1:40", "1:50", "1:60", "1:100",
                  "1:250", "1:500", "1:1000", "1:2000", "1:5000"]

    def _build_basemap_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="Basemap")
        self.basemap_info_data: dict | None = None

        pick = ttk.LabelFrame(frame, text="Orthomosaic (GeoTIFF)", padding=8)
        pick.pack(fill="x")
        pick.columnconfigure(0, weight=1)
        self.basemap_path_entry = ttk.Entry(pick)
        self.basemap_path_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(pick, text="Browse...",
                   command=self._basemap_browse).grid(row=0, column=1,
                                                      padx=(4, 0))
        ttk.Button(pick, text="Load info",
                   command=self._basemap_load_info).grid(row=0, column=2,
                                                         padx=(4, 0))

        ttk.Label(frame, text="Info:").pack(anchor="w", pady=(8, 0))
        self.basemap_info_text = _scrollable_text(frame, height=10)

        qrow = ttk.Frame(frame)
        qrow.pack(fill="x", pady=6)
        ttk.Label(qrow, text="Check GSD against scale:").pack(side="left")
        self.basemap_scale = ttk.Combobox(qrow, values=self.GSD_SCALES,
                                          state="readonly", width=10)
        self.basemap_scale.set("1:50")
        self.basemap_scale.pack(side="left", padx=4)
        ttk.Button(qrow, text="Check",
                   command=self._basemap_check_gsd).pack(side="left", padx=4)
        self.basemap_verdict = tk.Label(qrow, text="", font=(
            "TkDefaultFont", 10, "bold"), padx=8)
        self.basemap_verdict.pack(side="left", padx=4)
        self.basemap_gsd_msg = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.basemap_gsd_msg,
                  wraplength=700, justify="left").pack(anchor="w")

        act = ttk.Frame(frame)
        act.pack(pady=8)
        self.basemap_ov_btn = ttk.Button(act, text="Build overviews",
                                         command=self._basemap_overviews)
        self.basemap_ov_btn.pack(side="left", padx=4)
        ttk.Button(act, text="Attach to project",
                   command=self._basemap_attach).pack(side="left", padx=4)

    def _basemap_browse(self):
        p = filedialog.askopenfilename(
            title="Select orthomosaic GeoTIFF",
            filetypes=[("GeoTIFF", "*.tif *.tiff"), ("All files", "*.*")])
        if p:
            self.basemap_path_entry.delete(0, "end")
            self.basemap_path_entry.insert(0, p)

    def _basemap_load_info(self):
        tif = self.basemap_path_entry.get().strip()
        if not tif:
            messagebox.showerror("Basemap", "Choose a GeoTIFF first.")
            return
        crs = self.project.crs if self.project else ""
        try:
            info = runners.basemap_info(tif, project_crs=crs or None)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Basemap", f"Could not read GeoTIFF: {exc}")
            return
        self.basemap_info_data = info
        order = ["path", "crs", "width", "height", "bands", "gsd_m"]
        lines = []
        for k in order:
            if k in info:
                lines.append(f"{k}: {info[k]}")
        for k, v in info.items():
            if k not in order:
                lines.append(f"{k}: {v}")
        _set_text(self.basemap_info_text, "\n".join(lines))

    def _basemap_gsd(self) -> float | None:
        info = self.basemap_info_data or {}
        for k, v in info.items():
            if "gsd" in k.lower():
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return None

    def _basemap_check_gsd(self):
        gsd = self._basemap_gsd()
        if gsd is None:
            messagebox.showerror("GSD check",
                                 "Load the GeoTIFF info first (no GSD "
                                 "found).")
            return
        label = self.basemap_scale.get()
        try:
            res = runners.gsd_check(gsd, label)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("GSD check", str(exc))
            return
        verdict = res.get("verdict", "?")
        self.basemap_verdict.configure(
            text=verdict,
            bg="#1a9e4b" if verdict == "PASS" else "#e07b1a",
            fg="white")
        self.basemap_gsd_msg.set(res.get("message", ""))

    def _basemap_overviews(self):
        tif = self.basemap_path_entry.get().strip()
        if not tif:
            messagebox.showerror("Overviews", "Choose a GeoTIFF first.")
            return

        def work():
            return runners.build_basemap_overviews(tif)

        def done(res):
            _set_text(self.basemap_info_text, _fmt_dict(res))
            if self.project is not None:
                self.project.basemap_overviews_built = True
                self.project.save()
            messagebox.showinfo("Overviews", "Overview pyramid built.")

        self.run_worker(work, done, busy=[self.basemap_ov_btn])

    def _basemap_attach(self):
        if not self._require_project():
            return
        tif = self.basemap_path_entry.get().strip()
        if not tif or not os.path.isfile(tif):
            messagebox.showerror("Attach", "Choose an existing GeoTIFF.")
            return
        try:
            self.project.set_artifact("basemap_path", tif)
            self.project.save()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Attach", str(exc))
            return
        self._refresh_checklist()
        self.refresh_map()
        messagebox.showinfo("Basemap attached",
                           f"Basemap attached to project:\n{tif}")


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------

def build_app(license_status=None) -> SurveySuiteApp:
    """Create the main window (does not start the event loop)."""
    return SurveySuiteApp(license_status)


def main() -> None:
    """Launch the SurveySuite desktop app."""
    lic = check_license()
    if license_required() and not lic.valid:
        # Licensing is a warning, never a blocker: the app always runs.
        probe = tk.Tk()
        probe.withdraw()
        messagebox.showwarning(
            "SurveySuite license",
            f"License check: {lic.message}\n\n"
            "The app will run anyway (enforcement is off).")
        probe.destroy()
    build_app(lic).mainloop()


if __name__ == "__main__":
    main()
