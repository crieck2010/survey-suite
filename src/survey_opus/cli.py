"""Command-line interface for survey-opus (stdlib only).

Subcommands:
    survey-opus validate <rinex>          -- check a RINEX file pre-submission
    survey-opus submit <rinex> ...        -- upload to NGS OPUS
    survey-opus parse <report.txt> [--json] -- read an emailed OPUS solution report

All entry through ``main(argv)`` returning an int exit code, so the CLI is
testable without spawning a subprocess.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from survey_opus.client import (
    OpusError,
    parse_solution,
    solution_to_json,
    submit,
)
from survey_opus.rinex import RinexError, parse_header, validate_for_opus

NGS_ETIQUETTE_NOTE = """\
NGS OPUS etiquette — please be a good citizen:
  * Submit ONE job at a time; wait for the result email before submitting again.
  * Results arrive by EMAIL (typically 10-30 minutes). There is no status page
    and no polling API — do not re-submit to "check".
  * OPUS is a free public service of NOAA's National Geodetic Survey. Treat
    the shared compute queue with respect.
  * Double-check your antenna type and antenna height before submitting; bad
    metadata wastes NGS processing time and yields a useless solution.
  * Session guidance: static needs >= 2 hours of continuous data;
    rapid-static needs >= 15 minutes. Shorter sessions will likely be rejected.
"""


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def _print_header_summary(header) -> None:
    """Print the key fields of a parsed RINEX header."""
    start = header.start_time.isoformat(sep=" ", timespec="seconds") if header.start_time else "unknown"
    end = header.end_time.isoformat(sep=" ", timespec="seconds") if header.end_time else "unknown"
    print("RINEX header summary")
    print(f"  RINEX version : {header.rinex_version}")
    print(f"  Marker name   : {header.marker_name}")
    print(f"  Antenna type  : {header.antenna_type}")
    print(f"  Antenna height: {header.antenna_height:.3f} m")
    ap = header.approx_position
    if ap is not None:
        x, y, z = ap
        print(f"  Approx XYZ    : {x:.3f}, {y:.3f}, {z:.3f} m (ECEF)")
    else:
        print("  Approx XYZ    : unknown")
    print(f"  First obs     : {start}")
    print(f"  Last obs      : {end}")
    print(f"  Constellations: {', '.join(sorted(header.constellations)) or 'none'}")
    print(f"  Interval      : {header.interval if header.interval is not None else 'unknown'} s")


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.rinex)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    try:
        header = parse_header(path)
    except RinexError as exc:
        print(f"error: cannot parse RINEX header: {exc}", file=sys.stderr)
        return 2
    _print_header_summary(header)
    problems = validate_for_opus(header)
    if problems:
        print("\nNot submittable — problems found:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nOK: file looks submittable to OPUS.")
    return 0


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

def cmd_submit(args: argparse.Namespace) -> int:
    path = Path(args.rinex)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    try:
        receipt = submit(
            str(path),
            args.email,
            args.antenna_type,
            args.antenna_height,
            mode=args.mode,
            timeout=args.timeout,
        )
    except (OpusError, RinexError, ValueError) as exc:
        print(f"error: submission failed: {exc}", file=sys.stderr)
        return 2

    print("OPUS submission accepted for processing.")
    print(f"  RINEX file    : {receipt.rinex_filename}")
    print(f"  Email         : {receipt.email}")
    print(f"  Antenna type  : {receipt.antenna_type}")
    print(f"  Antenna height: {receipt.antenna_height:.3f} m")
    print(f"  Mode          : {receipt.mode}")
    print(f"  Endpoint      : {receipt.endpoint_url}")
    print(f"  Sequence no.  : {receipt.seqnum}")
    print(f"  HTTP status   : {receipt.response_status}")
    print("\nNGS will email the solution report (typically 10-30 minutes).")
    print("There is no status page to poll — submit one job at a time and wait.")
    return 0


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def _print_coordinate(label: str, coord) -> None:
    lon = coord.lon_deg
    hemi = "E" if lon >= 0 else "W"
    print(f"  {label} ({coord.frame}, epoch {coord.epoch}):")
    print(f"    lat {coord.lat_deg:.8f} deg, lon {abs(lon):.8f} deg {hemi}")
    print(f"    ellipsoidal height {coord.ell_ht_m:.3f} m")


def _print_grid(grid) -> None:
    print(f"  {grid.system} zone {grid.zone}:")
    print(f"    northing {grid.northing_m:.3f} m, easting {grid.easting_m:.3f} m")


def _print_solution_summary(solution) -> None:
    print("OPUS solution summary")
    print(f"  File           : {getattr(solution, 'file', 'unknown')}")
    print(f"  Email          : {getattr(solution, 'email', 'unknown')}")
    print(f"  Processed      : {getattr(solution, 'processing_date', 'unknown')}")
    if solution.nad83 is not None:
        _print_coordinate("NAD83", solution.nad83)
    if solution.itrf is not None:
        _print_coordinate("ITRF", solution.itrf)
    if solution.utm is not None:
        _print_grid(solution.utm)
    if solution.spc is not None:
        _print_grid(solution.spc)
    if solution.overall_rms_m is not None:
        print(f"  Overall RMS    : {solution.overall_rms_m * 1000:.1f} mm")
    if solution.pct_obs_used is not None:
        print(f"  Obs used       : {solution.pct_obs_used:.0f}%")
    if solution.pct_ambiguities_fixed is not None:
        print(f"  Ambiguities fixed: {solution.pct_ambiguities_fixed:.0f}%")
    if solution.peak_to_peak_m:
        pp = solution.peak_to_peak_m
        parts = ", ".join(f"{k}: {v * 1000:.1f} mm" for k, v in pp.items())
        print(f"  Peak-to-peak   : {parts}")
    if solution.base_stations:
        print(f"  Base stations  : {', '.join(solution.base_stations)}")
    print(f"  Software       : {getattr(solution, 'software', 'unknown')}")
    print(f"  Ephemeris      : {getattr(solution, 'ephemeris', 'unknown')}")


def cmd_parse(args: argparse.Namespace) -> int:
    path = Path(args.report)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"error: cannot read report: {exc}", file=sys.stderr)
        return 2
    try:
        solution = parse_solution(text)
    except OpusError as exc:
        print(f"error: not an OPUS solution report: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(solution_to_json(solution))
    else:
        _print_solution_summary(solution)
    return 0


# ---------------------------------------------------------------------------
# parser / main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="survey-opus",
        description=(
            "Client for NOAA NGS OPUS (Online Positioning User Service): "
            "validate RINEX observation files, submit them to OPUS, and parse "
            "the emailed solution reports."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p_validate = sub.add_parser(
        "validate",
        help="Check a RINEX observation file against OPUS requirements.",
        description="Parse a RINEX header and report any problems that would "
                    "block an OPUS submission. Exit 0 = submittable, 1 = problems, "
                    "2 = unreadable file.",
    )
    p_validate.add_argument("rinex", help="Path to the RINEX observation file.")
    p_validate.set_defaults(func=cmd_validate)

    p_submit = sub.add_parser(
        "submit",
        help="Submit a RINEX file to NGS OPUS.",
        description="Upload a RINEX observation file to NGS OPUS. NGS processes "
                    "it and emails the solution report to --email (typically "
                    "10-30 minutes). There is no status API to poll.",
        epilog=NGS_ETIQUETTE_NOTE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_submit.add_argument("rinex", help="Path to the RINEX observation file.")
    p_submit.add_argument("--email", required=True,
                          help="Email address that receives the solution report.")
    p_submit.add_argument("--antenna-type", required=True,
                          help="Antenna model as listed by NGS (e.g. TRM59900.00).")
    p_submit.add_argument("--antenna-height", required=True, type=float,
                          help="Antenna height in meters (ARP to marker).")
    p_submit.add_argument("--mode", choices=["static", "rapid-static"],
                          default="static",
                          help="OPUS variant: static (>= 2 h data) or rapid-static "
                               "(>= 15 min data). Default: static.")
    p_submit.add_argument("--timeout", type=int, default=60,
                          help="Upload HTTP timeout in seconds. Default: 60.")
    p_submit.set_defaults(func=cmd_submit)

    p_parse = sub.add_parser(
        "parse",
        help="Parse an OPUS solution report emailed by NGS.",
        description="Parse the solution report NGS emails after processing and "
                    "print a human summary, or machine-readable JSON with --json.",
    )
    p_parse.add_argument("report", help="Path to the OPUS report text file.")
    p_parse.add_argument("--json", action="store_true",
                         help="Print the solution as JSON instead of a summary.")
    p_parse.set_defaults(func=cmd_parse)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns an int exit code."""
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
