"""CLI: ``basemap info`` / ``basemap thumb`` / ``basemap overview``."""

import argparse
import json
import sys

from .errors import BasemapError
from .raster import GeoTIFFRaster
from .overview import build_overviews, overview_info
from .quality import quality_report
from .png import write_png


def cmd_info(args):
    if args.quality:
        rep = quality_report(args.tif, scales=args.scale or
                             ("1\"=50'", "1\"=100'"))
        if args.json:
            print(json.dumps(rep, indent=2, default=str))
        else:
            _print_quality(rep)
        return 0
    with GeoTIFFRaster(args.tif) as r:
        info = r.info()
    if args.json:
        print(json.dumps(info, indent=2, default=str))
    else:
        print(f"file:        {info['path']}")
        print(f"size:        {info['width']} x {info['height']} px, "
              f"{info['bands']} bands, {info['bits_per_sample']}-bit")
        print(f"compression: {info['compression']}"
              f"{' (tiled)' if info['tiled'] else ' (striped)'}"
              f"{' [BigTIFF]' if info['bigtiff'] else ''}")
        print(f"crs:         {info['crs']}")
        print(f"gsd:         {info['gsd_x_m'] * 100:.2f} x "
              f"{info['gsd_y_m'] * 100:.2f} cm/px")
        e = info["extent"]
        print(f"extent:      ({e['xmin']:.3f}, {e['ymin']:.3f}) -> "
              f"({e['xmax']:.3f}, {e['ymax']:.3f})")
        print(f"nodata:      {info['nodata']}")
        print(f"overviews:   {info['overview_levels']} levels")
    return 0


def _print_quality(rep):
    print(f"file:  {rep['path']}")
    print(f"size:  {rep['dimensions_px'][0]} x {rep['dimensions_px'][1]} px, "
          f"{rep['bands']} bands, {rep['compression']}")
    print(f"crs:   {rep['crs']}")
    print(f"gsd:   {rep['gsd_m']['x'] * 100:.2f} x "
          f"{rep['gsd_m']['y'] * 100:.2f} cm/px"
          + ("  (non-square pixels!)" if rep["non_square_pixels"] else ""))
    print(f"nodata: {rep['nodata']} "
          f"({rep['nodata_fraction'] * 100:.1f}% of sampled pixels)")
    for i, st in enumerate(rep["band_stats"]):
        print(f"band {i}: min {st['min']} max {st['max']} "
              f"mean {st['mean']:.1f}")
    print(f"overviews: {rep['overview_levels']} levels")
    for chk in rep["scale_checks"]:
        mark = "PASS" if chk["verdict"] == "PASS" else "WARN"
        print(f"[{mark}] {chk['message']}")


def cmd_thumb(args):
    with GeoTIFFRaster(args.tif) as r:
        rgb, w, h = r.render(max_px=args.width)
    write_png(args.out, rgb, w, h)
    print(f"wrote {args.out} ({w}x{h})")
    return 0


def cmd_overview(args):
    ovr = build_overviews(args.tif, min_size=args.min_size,
                          tile=args.tile)
    levels = overview_info(args.tif)
    print(f"wrote {ovr}")
    for lv in levels:
        print(f"  level: {lv['width']}x{lv['height']}"
              f"{' (internal)' if lv['internal'] else ' (sidecar)'}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="basemap",
                                 description="Drone basemap layer engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="report CRS, GSD, size, bands, "
                                    "compression, overviews")
    p.add_argument("tif")
    p.add_argument("--json", action="store_true")
    p.add_argument("--quality", action="store_true",
                   help="full quality report incl. GSD-vs-scale checks")
    p.add_argument("--scale", action="append",
                   help="plat scale label for the GSD check "
                        "(repeatable); default 1\"=50' and 1\"=100'")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("thumb", help="write a downsampled PNG preview")
    p.add_argument("tif")
    p.add_argument("out")
    p.add_argument("--width", type=int, default=800)
    p.set_defaults(func=cmd_thumb)

    p = sub.add_parser("overview", help="build .ovr pyramid sidecar")
    p.add_argument("tif")
    p.add_argument("--min-size", type=int, default=256)
    p.add_argument("--tile", type=int, default=512)
    p.set_defaults(func=cmd_overview)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except BasemapError as exc:
        print(f"basemap: error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
