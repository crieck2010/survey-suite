"""Field-to-finish workflow orchestration for the SurveySuite desktop app.

Every function here calls the survey-suite engines and formats results.
Zero surveying math lives in this module -- and zero Tk: it is importable
and testable without a display. The GUI in :mod:`suite.app` is a thin
layer over these runners.

Engine call shapes follow the INTEROP contracts of the four product
engines (survey-field, survey-adjust-workflow, survey-drafting,
survey-basemap); nothing here guesses at an engine API.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# import runner (survey-field)
# ---------------------------------------------------------------------------

@dataclass
class ImportResult:
    job_path: str
    summary: Dict[str, Any]
    issues: List[Dict[str, Any]]      # severity/code/message/session/point
    n_errors: int
    n_warnings: int
    ok: bool                          # no errors
    reproject: Optional[Dict[str, Any]] = None  # set when target_crs given:
    # {"applied", "n_points", "source_name", "target_name", "source_epsg",
    #  "target_epsg", "notes", "warnings"} -- warnings carry the
    # survey-crs datum-shift warnings for the import report view.


def run_import(csv_paths: List[str], job_path: str,
               project_name: str = "",
               thresholds: Optional[Dict[str, float]] = None,
               target_crs: Optional[str] = None) -> ImportResult:
    """Parse Emlid CSVs -> validate -> write .sfield.json job file.

    Multiple CSVs are merged into one project (points concatenated, base
    stations de-duplicated by position inside survey-field).

    When ``target_crs`` is given (an EPSG code or registry name, e.g.
    ``"EPSG:6539"``), geographic-CS exports are reprojected into the
    target on import via ``field.reproject`` (survey-field v0.2.0+,
    survey-crs backend); the job file keeps the ``crs_provenance`` block
    and the returned ``reproject`` dict surfaces the datum-shift
    warnings. Projected-in-a-different-CRS input is refused loudly --
    never silently mixed.
    """
    from field import emlid as emlid_mod
    from field.adapters import job_summary
    from field.jobfile import write_job
    from field.validate import has_errors, validate_project

    thresholds = thresholds or {}
    points, base_info, dialects = [], [], []
    for csv_path in csv_paths:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
            result = emlid_mod.parse_emlid_csv(fh)
        points.extend(result.points)
        base_info.extend(result.base_info)
        dialects.append(f"{os.path.basename(csv_path)}:{result.dialect}")
    if not points:
        raise ValueError("no survey points parsed from the selected CSVs")
    name = project_name or os.path.splitext(
        os.path.basename(csv_paths[0]))[0]
    project = emlid_mod.build_project(
        points, base_info, name,
        source_file=",".join(os.path.basename(p) for p in csv_paths))
    issues = validate_project(
        project,
        rms_lateral_warn=thresholds.get("rms_lateral", 0.02),
        rms_elev_warn=thresholds.get("rms_elev", 0.03),
        pdop_warn=thresholds.get("pdop", 3.0),
        baseline_warn_m=thresholds.get("baseline_km", 10.0) * 1000.0,
    )
    write_job(project, job_path)
    reproject = None
    if target_crs:
        try:
            from field.reproject import reproject_project
        except ImportError as exc:
            raise ValueError(
                "reproject-on-import needs survey-field 0.2.0 or newer "
                "(field.reproject); the installed survey-field is older. "
                "Upgrade the engine or turn the toggle off.") from exc
        try:
            report = reproject_project(project, target_crs)
        except Exception:
            # Never leave a half-reprojected job file behind: the GUI
            # surfaces the (already actionable) error via on_error.
            try:
                os.unlink(job_path)
            except OSError:
                pass
            raise
        # Persist the reprojected coordinates + crs_provenance block.
        write_job(project, job_path)
        prov = report.provenance or {}
        src = prov.get("source_crs", {})
        tgt = prov.get("target_crs", {})
        reproject = {
            "applied": report.applied,
            "n_points": report.n_points,
            "source_name": report.source_name,
            "target_name": report.target_name,
            "source_epsg": src.get("epsg"),
            "target_epsg": tgt.get("epsg"),
            "notes": list(report.notes),
            "warnings": list(report.warnings),
        }
    summary = job_summary(project)
    summary["dialects"] = dialects
    issue_dicts = [dict(severity=i.severity, code=i.code,
                        message=str(i), session_id=i.session_id,
                        point_name=i.point_name) for i in issues]
    n_errors = sum(1 for i in issues if i.severity == "error")
    n_warnings = sum(1 for i in issues if i.severity == "warning")
    return ImportResult(job_path=job_path, summary=summary,
                        issues=issue_dicts, n_errors=n_errors,
                        n_warnings=n_warnings,
                        ok=not has_errors(issues),
                        reproject=reproject)


def inspect_job(job_path: str) -> Dict[str, Any]:
    """Human-readable summary of an existing .sfield.json job."""
    from field.adapters import job_summary
    from field.jobfile import read_job
    return job_summary(read_job(job_path))


# ---------------------------------------------------------------------------
# weights (survey-adjust-workflow stochastic model)
# ---------------------------------------------------------------------------

def default_weights() -> Dict[str, Any]:
    from adjustflow import stochastic
    return stochastic.default_weights()


def validate_weights(cfg: Dict[str, Any]) -> List[str]:
    """Validate a weights config; returns a list of problem strings ([] = valid)."""
    from adjustflow import stochastic
    try:
        stochastic.validate_weights(cfg)
    except ValueError as exc:
        return [str(exc)]
    return []


def weights_summary(cfg: Dict[str, Any]) -> str:
    """One-paragraph-per-class plain-language summary of a weights config."""
    lines = []
    rtk = cfg.get("rtk", {})
    lines.append(
        "RTK: sigma = receiver RMS x {rms_scale} (floor {min_sigma_m} m, "
        "fallback {default_sigma_m} m); FLOAT/SINGLE policy: {float_policy}"
        .format(rms_scale=rtk.get("rms_scale", "?"),
                min_sigma_m=rtk.get("min_sigma_m", "?"),
                default_sigma_m=rtk.get("default_sigma_m", "?"),
                float_policy=rtk.get("float_policy", "?")))
    lvl = cfg.get("levels", {})
    lines.append(
        "Levels: sigma = {mm}/sqrt(km) (floor {min_sigma_m} m)".format(
            mm=lvl.get("mm_per_sqrt_km", "?"),
            min_sigma_m=lvl.get("min_sigma_m", "?")))
    ang = cfg.get("angles", {})
    lines.append(f"Angles: sigma = {ang.get('arcseconds', '?')} arcseconds.")
    dist = cfg.get("distances", {})
    lines.append(
        "Distances: sigma = {mm} mm + {ppm} ppm.".format(
            mm=dist.get("mm", "?"), ppm=dist.get("ppm", "?")))
    if cfg.get("datum_rename"):
        lines.append(f"Datum rename: {cfg['datum_rename']}")
    if cfg.get("datum_hold"):
        lines.append(f"Datum hold: {cfg['datum_hold']}")
    for i, ov in enumerate(cfg.get("overrides", [])):
        lines.append(
            f"Override {i + 1}: {ov.get('scope')}/{ov.get('class')} "
            f"match={ov.get('match', '-')} params={ov.get('params')}"
            + (f" (reason: {ov.get('reason')})" if ov.get("reason") else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# adjustment runner (survey-adjust-workflow)
# ---------------------------------------------------------------------------

@dataclass
class AdjustResult:
    valid: bool
    verdict: str                      # "VALID" | "NOT VALID"
    checks: List[Dict[str, Any]]      # criterion/detail/ok
    report_path: str
    sadj_path: Optional[str]
    adjusted_job_path: Optional[str]
    notes: List[str]
    n_points: int


def _sadj_points(rtk_res, level_res, trav_res) -> List[Dict[str, Any]]:
    """Adjusted points via adjustflow's builder (v0.1.1+).

    Delegates to ``adjustflow.cli._sadj_points`` rather than carrying a
    local mirror -- that function merges duplicate station names across
    the rtk/level-net/traverse paths (first non-null coordinate wins),
    which downstream drafting requires.
    """
    from adjustflow import cli as af_cli
    from adjustflow import report as report_mod
    return af_cli._sadj_points(report_mod.ReportData(
        project_name="", crs="", job_path="", job_sha256="",
        weights_path=None, weights_sha256=None, weights_cfg={},
        package_versions={}, paths_run=[],
        rtk=rtk_res, levelnet=level_res, traverse=trav_res))


def run_adjust(job_path: str, weights_cfg: Dict[str, Any], out_dir: str,
               name: str = "adjustment",
               paths: tuple = ("rtk", "levels"),
               traverse_path: Optional[str] = None,
               level_obs_path: Optional[str] = None,
               alpha: float = 0.05,
               snoop_threshold: float = 3.29) -> AdjustResult:
    """Run the adjustment workflow; mirrors ``adjustflow run``.

    Writes ``<name>.report.md``, ``<name>.sadj.json`` and
    ``<name>.adjusted.sfield.json`` into ``out_dir``. Returns the
    verdict -- the GUI must refuse drafting when ``valid`` is False.
    """
    from adjustflow import cli as af_cli
    from adjustflow import jobio, levelnet, report as report_mod
    from adjustflow import rtk, stochastic, traverse as trav_mod

    problems = validate_weights(weights_cfg)
    if problems:
        raise ValueError("invalid weights config: " + "; ".join(problems))
    os.makedirs(out_dir, exist_ok=True)

    run_paths = list(paths)
    if "traverse" in run_paths and not traverse_path:
        run_paths.remove("traverse")
    notes: List[str] = []
    if "traverse" in paths and not traverse_path:
        notes.append("traverse path skipped: no traverse file supplied")

    project = jobio.read_job_file(job_path)
    level_obs = (levelnet.load_level_observations(level_obs_path)
                 if level_obs_path else None)

    rtk_res = level_res = trav_res = None
    if "rtk" in run_paths:
        rtk_res = rtk.adjust_rtk_points(project, weights_cfg)
        notes.extend(rtk_res.warnings[:10])
    if "levels" in run_paths:
        level_res = levelnet.adjust_level_network(
            project, weights_cfg, level_obs=level_obs, alpha=alpha,
            snoop_threshold=snoop_threshold)
        notes.extend(level_res.warnings[:10])
    if "traverse" in run_paths:
        trav_res = trav_mod.adjust_traverse(
            trav_mod.load_traverse(traverse_path), weights_cfg,
            alpha=alpha, snoop_threshold=snoop_threshold)
        notes.extend(trav_res.warnings[:10])

    data = report_mod.ReportData(
        project_name=project.name, crs=project.crs,
        job_path=job_path, job_sha256=jobio.sha256_file(job_path),
        weights_path=None,
        weights_sha256=jobio.sha256_json(weights_cfg),
        weights_cfg=weights_cfg, package_versions=jobio.package_versions(),
        paths_run=run_paths, rtk=rtk_res, levelnet=level_res,
        traverse=trav_res, notes=notes)
    data.validity = af_cli._validity_checks(data)  # documented handoff

    report_path = os.path.join(out_dir, f"{name}.report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report_mod.build_report(data))

    sadj_points = _sadj_points(rtk_res, level_res, trav_res)
    sadj_path = os.path.join(out_dir, f"{name}.sadj.json")
    jobio.write_sadj(
        sadj_path, job_path=job_path, weights_path=None,
        weights_cfg=weights_cfg, paths_run=run_paths,
        points=sadj_points, validity=data.validity,
        report_path=report_path, notes=notes)

    adjusted_job_path = None
    if rtk_res is not None:
        by_name = {p.name: {"easting": p.easting, "northing": p.northing,
                            "elevation": p.elevation, "sigma_e": p.sigma_e,
                            "sigma_n": p.sigma_n, "sigma_u": p.sigma_u}
                   for p in rtk_res.points}
        adjusted_job_path = os.path.join(
            out_dir, f"{name}.adjusted.sfield.json")
        jobio.write_adjusted_job_revision(project, by_name,
                                          adjusted_job_path)

    valid = bool(data.validity["valid"])
    checks = [{"criterion": c, "ok": bool(ok), "detail": d}
              for c, ok, d in data.validity["checks"]]
    return AdjustResult(
        valid=valid, verdict="VALID" if valid else "NOT VALID",
        checks=checks, report_path=report_path, sadj_path=sadj_path,
        adjusted_job_path=adjusted_job_path, notes=notes,
        n_points=len(sadj_points))


def read_report(report_path: str) -> str:
    with open(report_path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# drafting runner (survey-drafting)
# ---------------------------------------------------------------------------

def style_template() -> Dict[str, Any]:
    from drafting import style_template as _st
    return _st()


def validate_style(style_dict: Dict[str, Any]) -> List[str]:
    """Validate a style dict via drafting's own loader; [] = valid."""
    import tempfile
    from drafting import load_style
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False,
                                         encoding="utf-8") as fh:
            json.dump(style_dict, fh)
            tmp = fh.name
        load_style(tmp)
        return []
    except Exception as exc:  # noqa: BLE001 -- report, don't raise
        return [str(exc)]
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def parcel_template(point_names: List[str], units: str = "ft") -> Dict[str, Any]:
    """A closed straight-leg parcel through the given points, in order."""
    segs = [{"from": a, "to": b}
            for a, b in zip(point_names, point_names[1:] + point_names[:1])]
    return {"format": "survey-drafting/parcel", "schema_version": 1,
            "name": "Lot 1", "units": units, "segments": segs}


def run_draft(sadj_path: str, parcel: Dict[str, Any],
              style: Optional[Dict[str, Any]], out_pdf: str,
              options: Optional[Dict[str, Any]] = None,
              basemap_source: Any = None) -> Dict[str, Any]:
    """Compose plat/plan/map PDF. Raises drafting.sadj.DraftRefused when
    the adjustment is not VALID -- the gate is absolute, no override."""
    import tempfile
    from drafting import compose_deliverable, load_style

    opts = dict(options or {})
    if basemap_source is not None:
        opts["basemap"] = basemap_source
    with tempfile.TemporaryDirectory() as tmp:
        parcel_path = os.path.join(tmp, "parcel.json")
        with open(parcel_path, "w", encoding="utf-8") as fh:
            json.dump(parcel, fh)
        if style is None:
            from drafting.styles import DEFAULT_STYLE
            st_obj = DEFAULT_STYLE
        else:
            style_path = os.path.join(tmp, "style.json")
            with open(style_path, "w", encoding="utf-8") as fh:
                json.dump(style, fh)
            st_obj = load_style(style_path)
        manifest = compose_deliverable(sadj_path, parcel_path, st_obj,
                                       out_pdf, opts)
    return manifest


# ---------------------------------------------------------------------------
# basemap runner (survey-basemap)
# ---------------------------------------------------------------------------

def basemap_info(tif_path: str,
                 project_crs: Optional[str] = None) -> Dict[str, Any]:
    """Info dict for a GeoTIFF (CRS, GSD, size, bands, overviews)."""
    from basemap.drafting_adapter import GeoTIFFRasterSource
    with GeoTIFFRasterSource(tif_path, project_crs=project_crs) as src:
        info = src.info()
    info["path"] = tif_path
    return info


def build_basemap_overviews(tif_path: str) -> Dict[str, Any]:
    from basemap.overview import build_overviews, overview_info
    build_overviews(tif_path)
    return overview_info(tif_path)


def gsd_check(gsd_m: float, scale_label: str) -> Dict[str, Any]:
    """PASS/WARN verdict: is the basemap GSD fine enough for the scale?"""
    from basemap.quality import check_scale
    return check_scale(gsd_m, scale_label)


def make_basemap_source(tif_path: str, project_crs: Optional[str] = None,
                        opacity: float = 1.0, max_render_px: int = 4096):
    """A GeoTIFFRasterSource ready for run_draft's basemap_source.

    The caller owns closing it (context manager). Kept open across the
    compose call.
    """
    from basemap.drafting_adapter import GeoTIFFRasterSource
    return GeoTIFFRasterSource(tif_path, project_crs=project_crs,
                               opacity=opacity, max_render_px=max_render_px)


# ---------------------------------------------------------------------------
# map canvas data (Tk-free geometry)
# ---------------------------------------------------------------------------

def map_points(job_path: Optional[str] = None,
               sadj_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Points for the map canvas: name, E/N, solution, sigmas, held.

    Prefers adjusted coordinates when a .sadj.json is given; falls back
    to the raw job. Solution status always comes from the job file.
    """
    pts: Dict[str, Dict[str, Any]] = {}
    if job_path:
        from field.jobfile import read_job
        project = read_job(job_path)
        for sess in project.sessions:
            for p in sess.points:
                if p.has_projected():
                    pts[p.name] = {
                        "name": p.name, "easting": p.easting,
                        "northing": p.northing, "elevation": p.elevation,
                        "solution": p.solution, "code": p.code,
                        "sigma_e": None, "sigma_n": None, "held": False,
                        "source": "job"}
        for b in project.base_stations:
            pts[b.id] = {"name": b.id, "easting": b.easting,
                         "northing": b.northing, "elevation": b.elevation,
                         "solution": "BASE", "code": "BASE",
                         "sigma_e": None, "sigma_n": None, "held": True,
                         "source": "job"}
    if sadj_path:
        from drafting.sadj import read_sadj
        doc = read_sadj(sadj_path)
        for p in doc.points:
            if p.easting is None or p.northing is None:
                continue
            rec = pts.get(p.name, {"name": p.name})
            rec.update({"easting": p.easting, "northing": p.northing,
                        "elevation": p.elevation, "sigma_e": p.sigma_e,
                        "sigma_n": p.sigma_n, "held": bool(p.held),
                        "source": p.source})
            pts[p.name] = rec
    return sorted(pts.values(), key=lambda r: r["name"])


def map_extent(points: List[Dict[str, Any]]) -> Optional[tuple]:
    """(xmin, ymin, xmax, ymax) over point E/N; None when empty."""
    es = [p["easting"] for p in points if p.get("easting") is not None]
    ns = [p["northing"] for p in points if p.get("northing") is not None]
    if not es:
        return None
    return (min(es), min(ns), max(es), max(ns))
