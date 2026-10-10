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
              basemap_source: Any = None,
              extra_layers: Optional[Dict[str, list]] = None
              ) -> Dict[str, Any]:
    """Compose plat/plan/map PDF. Raises drafting.sadj.DraftRefused when
    the adjustment is not VALID -- the gate is absolute, no override.

    ``extra_layers`` ({layer_name: [entity, ...]}) is merged into the
    deliverable's layers -- the figures-to-plat path (see
    :func:`figures_extra_layers`). Requires survey-drafting 0.1.3+.
    """
    import tempfile
    from drafting import compose_deliverable, load_style

    opts = dict(options or {})
    if basemap_source is not None:
        opts["basemap"] = basemap_source
    if extra_layers is not None:
        opts["extra_layers"] = extra_layers
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


# ---------------------------------------------------------------------------
# figures runner (survey-linework)
# ---------------------------------------------------------------------------

class FiguresRefused(ValueError):
    """Strict gate: flagged linework was refused from reaching drafting.

    Raised by :func:`figures_extra_layers` when ``strict`` is true and the
    figures carry any QA flags. There is no override -- fix the field
    coding or turn strict mode off in the Figures toolbox.
    """


@dataclass
class FiguresBuildResult:
    figures_path: str
    counts: Dict[str, Any]
    flags: List[Dict[str, str]]      # figure/flag/detail
    warnings: List[str]
    codeset_name: str
    ok: bool                        # built without a LineworkError


#: Plain-language explanations for survey-linework QA flag codes, shown
#: in the Figures toolbox QA panel (Civil 3D surfaces problems rather
#: than hiding them).
FLAG_EXPLANATIONS = {
    "closure_exceeds_tolerance":
        "The figure's closing misclosure is larger than the figure-prefix "
        "database allows. Check for a bad shot, a mis-typed point name, "
        "or a wrong curve radius in the field codes.",
    "unclosed_expected_closed":
        "This figure was expected to close (per its prefix entry) but was "
        "left open -- the closing shot or *cl code may be missing.",
    "figure_never_ended":
        "The figure was still open when the job ended: no end code was "
        "shot for it. It was emitted as an open figure so no shots are "
        "lost.",
    "offset_figure":
        "Informational: this is a generated offset of another figure, "
        "not field linework itself.",
}


def resolve_codeset(source: str):
    """A ``LineworkCodeSet`` from ``"preset:emlid"``, ``"preset:civil3d"``,
    or a JSON file path. Config problems raise ``ValueError`` naming the
    exact issue (fail loud, like the engine)."""
    from linework.codeset import (builtin_codeset, load_codeset)
    from linework.errors import LineworkError
    try:
        if source == "preset:emlid":
            return builtin_codeset("emlid")
        if source == "preset:civil3d":
            return builtin_codeset("civil3d")
        if source.startswith("preset:"):
            raise ValueError(
                f"unknown code-set preset {source!r}; choose "
                "'preset:emlid', 'preset:civil3d', or a JSON file path")
        return load_codeset(source)
    except LineworkError as exc:
        raise ValueError(f"code set invalid: {exc}") from exc


def _default_keys():
    from linework.keys import DescriptionKeys, keys_template
    return DescriptionKeys.from_dict(keys_template())


def _default_prefixes():
    from linework.prefixes import FigurePrefixDB, prefixes_template
    return FigurePrefixDB.from_dict(prefixes_template())


def _sha256_file(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_figures_build(job_path: str, codeset_source: str, out_path: str,
                      keys_path: Optional[str] = None,
                      prefixes_path: Optional[str] = None,
                      offset_sagitta_m: float = 0.01) -> FiguresBuildResult:
    """Build figures from a .sfield.json job; mirrors ``linework build``.

    Writes the versioned figures JSON to ``out_path``. ``keys_path`` /
    ``prefixes_path`` default to the documented built-in templates.
    Engine problems raise ``ValueError`` with the engine's message.
    """
    from field.jobfile import read_job
    from linework.errors import LineworkError
    from linework.figures import build_figures
    from linework.interchange import write_figures
    from linework.keys import load_keys
    from linework.prefixes import load_prefixes

    codeset = resolve_codeset(codeset_source)
    try:
        keys = load_keys(keys_path) if keys_path else _default_keys()
        prefixes = (load_prefixes(prefixes_path) if prefixes_path
                    else _default_prefixes())
    except LineworkError as exc:
        raise ValueError(f"linework config invalid: {exc}") from exc
    project = read_job(job_path)
    try:
        result = build_figures(
            project, codeset, keys, prefixes,
            job_sha256=_sha256_file(job_path),
            offset_chord_sagitta_m=offset_sagitta_m)
    except LineworkError as exc:
        raise ValueError(f"figure build failed: {exc}") from exc
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    write_figures(result, out_path)
    return FiguresBuildResult(
        figures_path=out_path, counts=result.counts(),
        flags=[dict(f) for f in result.flags],
        warnings=list(result.warnings),
        codeset_name=codeset.name, ok=True)


def read_figures(figures_path: str) -> Dict[str, Any]:
    """Read a figures JSON file (rejects newer schemas loudly)."""
    from linework.interchange import read_figures as _read
    return _read(figures_path)


def figure_records(figures_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One summary dict per figure for the figure tree.

    Keys: id, base_code, prefix, layer, style, closed, close_method,
    n_vertices, misclosure_m, n_flags, offset_of.
    """
    recs = []
    for f in figures_data.get("figures", []):
        flags = f.get("flags", [])
        recs.append({
            "id": f.get("id"), "base_code": f.get("base_code"),
            "prefix": f.get("prefix"), "layer": f.get("layer"),
            "style": f.get("style"), "closed": bool(f.get("closed")),
            "close_method": f.get("close_method"),
            "n_vertices": len(f.get("vertices", [])),
            "misclosure_m": f.get("misclosure_m"),
            "n_flags": len(flags),
            "flag_codes": [fl.get("flag") for fl in flags],
            "offset_of": f.get("offset_of"),
        })
    return recs


def qa_flag_list(figures_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Every QA flag with a plain-language explanation.

    Keys: figure, flag, detail, explanation.
    """
    out = []
    for fl in figures_data.get("report", {}).get("flags", []):
        code = fl.get("flag", "")
        out.append({
            "figure": fl.get("figure", ""),
            "flag": code,
            "detail": fl.get("detail", ""),
            "explanation": FLAG_EXPLANATIONS.get(
                code, "See the survey-linework docs for this flag code."),
        })
    for w in figures_data.get("report", {}).get("warnings", []):
        out.append({"figure": "", "flag": "warning", "detail": w,
                    "explanation": "Build warning from survey-linework."})
    return out


def figures_strict_problems(figures_data: Dict[str, Any]) -> List[str]:
    """Non-empty when the strict gate must refuse drafting.

    Mirrors ``linework build --strict``: any QA flag is a refusal reason.
    """
    problems = []
    for fl in qa_flag_list(figures_data):
        if fl["flag"] == "warning":
            continue
        who = f"[{fl['figure']}] " if fl["figure"] else ""
        problems.append(f"{who}{fl['flag']}: {fl['detail']}")
    return problems


def figure_stats(figures_data: Dict[str, Any], figure_id: str,
                 chord_sagitta_m: float = 0.01) -> Dict[str, Any]:
    """Vertex count, chorded length, closure, area/perimeter, provenance.

    Area/perimeter come from survey-cogo on closed figures only.
    """
    from linework.interchange import figures_from_dict
    figs = {f.id: f for f in figures_from_dict(figures_data)}
    fig = figs.get(figure_id)
    if fig is None:
        raise ValueError(f"unknown figure {figure_id!r}")
    import math
    pts = fig.chorded_points(chord_sagitta_m)
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1])
                 for a, b in zip(pts, pts[1:]))
    stats: Dict[str, Any] = {
        "id": fig.id, "layer": fig.layer, "style": fig.style,
        "closed": fig.closed, "close_method": fig.close_method,
        "n_vertices": len(fig.vertices), "n_chorded": len(pts),
        "length_m": length, "misclosure_m": fig.misclosure_m,
        "offset_of": fig.offset_of,
        "area_m2": None, "perimeter_m": None,
        "provenance": fig.provenance,
    }
    if fig.closed:
        from linework.adapters import figures_to_cogo
        from cogo.area import polygon_area, polygon_perimeter
        cogo_pts = figures_to_cogo(figures_data,
                                   chord_sagitta_m=chord_sagitta_m)[figure_id]
        stats["area_m2"] = polygon_area(cogo_pts)
        stats["perimeter_m"] = polygon_perimeter(cogo_pts)
    return stats


def figures_canvas_data(figures_data: Dict[str, Any],
                        chord_sagitta_m: float = 0.01) -> List[Dict[str, Any]]:
    """Chorded polylines for the map canvas.

    Returns [{id, pts: [(x, y)...], closed}]; arcs are chorded within
    ``chord_sagitta_m`` (there is no arc entity on the canvas).
    """
    from linework.interchange import figures_from_dict
    out = []
    for fig in figures_from_dict(figures_data):
        pts = fig.chorded_points(chord_sagitta_m)
        out.append({"id": fig.id,
                    "pts": [(p[0], p[1]) for p in pts],
                    "closed": fig.closed})
    return out


def figures_extra_layers(figures_path: str, strict: bool = True,
                         chord_sagitta_m: float = 0.01,
                         include_points: bool = True) -> Dict[str, list]:
    """Drafting layer entities for a figures file.

    Raises :class:`FiguresRefused` naming every QA flag when ``strict``
    is true and the figures carry flags -- the gate before figures reach
    the plat. Feed the result into ``run_draft(..., extra_layers=...)``.
    """
    from linework.adapters import figures_to_drafting_layers
    data = read_figures(figures_path)
    if strict:
        problems = figures_strict_problems(data)
        if problems:
            raise FiguresRefused(
                "strict mode: flagged linework refused from drafting:\n"
                + "\n".join(f"  - {p}" for p in problems))
    return figures_to_drafting_layers(data, chord_sagitta_m=chord_sagitta_m,
                                      include_points=include_points)
