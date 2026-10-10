"""Command-line interface: crs list / search / info / convert."""
from __future__ import annotations

import argparse
import sys

from . import picker, registry, transforms
from .errors import CrsError


def _fmt_entry(e) -> str:
    unit = {"m": "m", "ftUS": "ftUS", "ft": "ft", "deg": "deg"}[e.unit]
    zone = " [%s]" % e.zone if e.zone else ""
    return "EPSG:%-6d %-52s %-4s %s%s" % (e.epsg, e.name, unit, e.datum, zone)


def cmd_list(args) -> int:
    entries = registry.list_entries()
    if args.group:
        entries = [e for e in entries if e.group == args.group]
    if args.state:
        entries = [e for e in picker.zones_for_state(args.state)]
    for e in entries:
        print(_fmt_entry(e))
    print("%d entries" % len(entries), file=sys.stderr)
    return 0


def cmd_search(args) -> int:
    hits = picker.search(args.query, limit=args.limit)
    for e in hits:
        print(_fmt_entry(e))
    print("%d matches" % len(hits), file=sys.stderr)
    return 0


def cmd_info(args) -> int:
    print(picker.by_epsg(args.epsg).describe())
    return 0


def cmd_convert(args) -> int:
    src = picker.by_epsg(args.from_epsg)
    if src.is_projected:
        if args.easting is None or args.northing is None:
            print("error: projected source needs --easting and --northing",
                  file=sys.stderr)
            return 2
        x, y = args.easting, args.northing
    else:
        if args.lat is None or args.lon is None:
            print("error: geographic source needs --lat and --lon",
                  file=sys.stderr)
            return 2
        x, y = args.lon, args.lat
    r = transforms.transform_coords(x, y, args.from_epsg, args.to_epsg,
                                    h=args.h or 0.0)
    dst = picker.by_epsg(args.to_epsg)
    if dst.is_projected:
        print("easting=%.4f northing=%.4f h=%.3f unit=%s"
              % (r.x, r.y, r.h, r.unit))
    else:
        print("lon=%.9f lat=%.9f h=%.3f" % (r.x, r.y, r.h))
    print("datum: %s -> %s  (%s; ~%.3g m horizontal)"
          % (r.from_datum, r.to_datum, r.datum_path.method,
             r.datum_path.accuracy_horizontal_m))
    print("backend: %s" % r.backend)
    for w in r.warnings:
        print("warning: %s" % w)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crs",
                                description="survey-crs: CRS registry and "
                                            "coordinate transforms")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="list registry entries")
    pl.add_argument("--group", choices=["spcs", "utm", "geographic"])
    pl.add_argument("--state", help="state name or abbreviation, e.g. NY")
    pl.set_defaults(func=cmd_list)

    ps = sub.add_parser("search", help="search the registry")
    ps.add_argument("query")
    ps.add_argument("--limit", type=int, default=20)
    ps.set_defaults(func=cmd_search)

    pi = sub.add_parser("info", help="describe one CRS")
    pi.add_argument("epsg", type=int)
    pi.set_defaults(func=cmd_info)

    pc = sub.add_parser("convert", help="convert coordinates between CRSs")
    pc.add_argument("--from-epsg", dest="from_epsg", type=int, required=True)
    pc.add_argument("--to-epsg", dest="to_epsg", type=int, required=True)
    pc.add_argument("--lat", type=float)
    pc.add_argument("--lon", type=float)
    pc.add_argument("--easting", type=float)
    pc.add_argument("--northing", type=float)
    pc.add_argument("--h", type=float, default=0.0,
                    help="ellipsoidal height, metres")
    pc.set_defaults(func=cmd_convert)
    return p


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except CrsError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
