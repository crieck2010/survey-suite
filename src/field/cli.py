"""Command-line interface for survey-field.

Commands
--------
``import``   Parse an Emlid Flow / ReachView 3 CSV export into a canonical
             ``.sfield.json`` job file. Prints the validation report.
``inspect``  Print a human-readable summary of a job file.
``export``   Write a job file back out as flattened CSV or canonical JSON.

Exit codes: 0 = success (warnings allowed); 1 = validation errors or failure.
"""

from __future__ import annotations

import argparse
import csv
import sys

from . import __version__
from .adapters import job_summary
from .emlid import import_emlid_csv
from .jobfile import read_job, write_job
from .reproject import CrsReprojectError, reproject_project
from .validate import has_errors, validate_project


def _cmd_import(args: argparse.Namespace) -> int:
    try:
        project = import_emlid_csv(args.csv, project_name=args.name)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    crs_notes = []
    crs_warnings = []
    if args.target_crs:
        # Optional survey-crs backend; failures refuse loudly before anything
        # is written (no job file on a CRS refusal).
        try:
            report = reproject_project(project, args.target_crs)
        except CrsReprojectError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        crs_notes = report.notes
        crs_warnings = report.warnings
    issues = validate_project(
        project,
        rms_lateral_warn=args.rms_lateral,
        rms_elev_warn=args.rms_elev,
        pdop_warn=args.pdop,
        baseline_warn_m=args.max_baseline * 1000.0,
    )
    write_job(project, args.output)
    summary = job_summary(project)
    print(f"project : {summary['name']}")
    print(f"crs     : {summary['crs'] or '(not recorded)'}")
    print(f"bases   : {summary['n_base_stations']}  "
          f"sessions: {summary['n_sessions']}  points: {summary['n_points']}")
    print(f"solutions: " + ", ".join(
        f"{k}={v}" for k, v in sorted(summary["solutions"].items())))
    print(f"wrote   : {args.output}")
    for note in crs_notes:
        print(f"crs note: {note}")
    for warning in crs_warnings:
        # Datum-shift / area-of-use warnings from survey-crs are surfaced
        # here in the import report, never buried in the job file alone.
        print(f"crs warning: {warning}")
    for issue in issues:
        print(str(issue), file=sys.stderr if issue.severity == "error" else sys.stdout)
    n_err = sum(1 for i in issues if i.severity == "error")
    n_warn = sum(1 for i in issues if i.severity == "warning")
    print(f"validation: {n_err} error(s), {n_warn} warning(s)")
    return 1 if has_errors(issues) else 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    try:
        project = read_job(args.job)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    summary = job_summary(project)
    print(f"project : {summary['name']}")
    print(f"crs     : {summary['crs'] or '(not recorded)'}")
    print(f"source  : {', '.join(project.source_files) or '(unknown)'}")
    prov = project.crs_provenance
    if prov:
        src = prov.get("source_crs", {})
        tgt = prov.get("target_crs", {})
        tr = prov.get("transform", {})
        dp = tr.get("datum_path", {})
        print("crs provenance:")
        as_rec = src.get("as_recorded_in_csv")
        suffix = f"  [as recorded: {as_rec!r}]" if as_rec not in (None, src.get("name")) else ""
        print(f"  source   : {src.get('name', '?')} (EPSG:{src.get('epsg', '?')}){suffix}")
        print(f"  target   : {tgt.get('name', '?')} (EPSG:{tgt.get('epsg', '?')})")
        status = (f"applied to {tr.get('n_points')} point(s)"
                  if tr.get("applied") else "not applied (already in target CRS)")
        print(f"  transform: {status} via survey-crs {tr.get('survey_crs_version', '?')} "
              f"(backend: {tr.get('backend', '?')}) at {tr.get('timestamp', '?')}")
        print(f"  datum    : {dp.get('from_datum', '?')} -> {dp.get('to_datum', '?')} "
              f"[{dp.get('method', '?')}, ~{dp.get('accuracy_horizontal_m', '?')} m horizontal, "
              f"{dp.get('region', '?')}]")
        for w in tr.get("warnings", []):
            print(f"  warning  : {w}")
        for note in prov.get("notes", []):
            print(f"  note     : {note}")
    print(f"bases   : {summary['n_base_stations']}")
    for base in project.base_stations:
        pos = (f"E {base.easting} N {base.northing} EL {base.elevation}"
               if base.easting is not None else
               f"lon {base.longitude} lat {base.latitude}")
        print(f"  {base.id}: {pos}  ({base.n_points} pts)")
    print(f"sessions: {summary['n_sessions']}  points: {summary['n_points']}")
    for s in summary["sessions"]:
        print(f"  {s['id']}: base={s['base_station_id']} "
              f"date={s['date'] or '?'} n={s['n_points']}")
    print(f"solutions: " + ", ".join(
        f"{k}={v}" for k, v in sorted(summary["solutions"].items())))
    if args.issues:
        issues = validate_project(project)
        if not issues:
            print("validation: clean")
        for issue in issues:
            print(str(issue))
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    try:
        project = read_job(args.job)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        write_job(project, args.output)  # canonical pretty JSON
    else:
        with open(args.output, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                "session", "name", "code", "description",
                "easting", "northing", "elevation",
                "longitude", "latitude", "ellipsoidal_height",
                "solution", "rms_e", "rms_n", "rms_u", "rms_lateral",
                "antenna_height_m", "pdop", "baseline_m",
                "averaging_start", "averaging_end", "samples",
            ])
            for session in project.sessions:
                for p in session.points:
                    writer.writerow([
                        session.id, p.name, p.code, p.description,
                        p.easting, p.northing, p.elevation,
                        p.longitude, p.latitude, p.ellipsoidal_height,
                        p.solution, p.rms_e, p.rms_n, p.rms_u, p.rms_lateral,
                        p.antenna_height_m, p.pdop, p.baseline_m,
                        p.averaging_start, p.averaging_end, p.samples,
                    ])
    print(f"wrote: {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="field",
        description="survey-field: field-data import engine for the land-surveying suite")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="import an Emlid CSV export into a job file")
    p_import.add_argument("csv", help="Emlid Flow / ReachView 3 CSV export")
    p_import.add_argument("-o", "--output", required=True, help="output .sfield.json job file")
    p_import.add_argument("--name", default=None, help="project name (default: CSV filename)")
    p_import.add_argument("--rms-lateral", type=float, default=0.050,
                          help="lateral RMS warning threshold, metres (default 0.050)")
    p_import.add_argument("--rms-elev", type=float, default=0.100,
                          help="elevation RMS warning threshold, metres (default 0.100)")
    p_import.add_argument("--pdop", type=float, default=6.0,
                          help="PDOP warning threshold (default 6.0)")
    p_import.add_argument("--max-baseline", type=float, default=20.0,
                          help="baseline warning threshold, km (default 20)")
    p_import.add_argument("--target-crs", default=None, metavar="CRS",
                          help="reproject a geographic-CS export into this CRS on import: "
                               "an EPSG code ('EPSG:6539', '6539') or a survey-crs registry "
                               "name ('New York Long Island (ftUS)'). Requires the optional "
                               "survey-crs package (pip install survey-crs). Projected-CS "
                               "exports are only accepted when they already match the target; "
                               "a different projected CRS is refused, never silently mixed.")
    p_import.set_defaults(func=_cmd_import)

    p_inspect = sub.add_parser("inspect", help="summarise a job file")
    p_inspect.add_argument("job", help=".sfield.json job file")
    p_inspect.add_argument("--issues", action="store_true",
                           help="also print the validation report")
    p_inspect.set_defaults(func=_cmd_inspect)

    p_export = sub.add_parser("export", help="export a job file to CSV or canonical JSON")
    p_export.add_argument("job", help=".sfield.json job file")
    p_export.add_argument("-o", "--output", required=True, help="output file")
    p_export.add_argument("--format", choices=["csv", "json"], default="csv")
    p_export.set_defaults(func=_cmd_export)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
