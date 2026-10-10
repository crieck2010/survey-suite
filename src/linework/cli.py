"""CLI: linework build | keys-template | codeset-template | prefixes-template."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

from . import __version__
from .codeset import builtin_codeset, codeset_template, load_codeset
from .errors import LineworkError
from .figures import FigureBuilder
from .interchange import write_figures
from .keys import keys_template, load_keys
from .prefixes import load_prefixes, prefixes_template

EXIT_OK = 0
EXIT_ERROR = 1       # fail-loud build/config error
EXIT_STRICT = 2      # --strict: build produced flags


def _read_job(path: str):
    try:
        from field.jobfile import read_job
    except ImportError as exc:
        raise LineworkError(
            "linework build needs the survey-field engine to read "
            ".sfield.json job files "
            "(pip install git+https://github.com/crieck2010/survey-field)"
        ) from exc
    try:
        return read_job(path)
    except (OSError, ValueError) as exc:
        raise LineworkError(f"cannot read job file {path}: {exc}") from exc


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _cmd_build(args: argparse.Namespace) -> int:
    try:
        codeset = (builtin_codeset(args.preset) if args.preset
                   else load_codeset(args.codeset))
        keys = load_keys(args.keys)
        prefixes = load_prefixes(args.prefixes)
    except LineworkError as exc:
        print(f"linework: config error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    try:
        project = _read_job(args.job)
        digest = _sha256_file(args.job)
        builder = FigureBuilder(codeset, keys, prefixes,
                                offset_chord_sagitta_m=args.offset_sagitta)
        result = builder.build(project, job_sha256=digest)
        write_figures(result, args.out)
    except LineworkError as exc:
        print(f"linework: build failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    counts = result.counts()
    print(f"figures: {counts['n_figures']} "
          f"({counts['n_closed_figures']} closed, "
          f"{counts['n_open_figures']} open, "
          f"{counts['n_offset_figures']} offset) from "
          f"{counts['n_coded_points']} coded points "
          f"({counts['n_uncoded_points']} uncoded) -> {args.out}")
    for fl in result.flags:
        print(f"flag [{fl['figure']}] {fl['flag']}: {fl['detail']}")
    for w in result.warnings:
        print(f"warning: {w}")
    if args.strict and result.flags:
        print("linework: --strict: build produced flags", file=sys.stderr)
        return EXIT_STRICT
    return EXIT_OK


def _cmd_template(args: argparse.Namespace) -> int:
    if args.command == "keys-template":
        doc = keys_template()
    elif args.command == "codeset-template":
        doc = codeset_template(args.preset)
    else:
        doc = prefixes_template()
    json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="linework",
        description="Field-coding/linework engine: coded points in, "
                    "drafted figures out.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build figures from a .sfield.json job")
    b.add_argument("--job", required=True, help=".sfield.json job file")
    b.add_argument("--codeset", default=None,
                   help="linework code-set JSON (or use --preset)")
    b.add_argument("--preset", choices=["emlid", "civil3d"], default=None,
                   help="built-in code-set preset (default: emlid)")
    b.add_argument("--keys", required=True, help="description-keys JSON")
    b.add_argument("--prefixes", required=True,
                   help="figure-prefix database JSON")
    b.add_argument("--out", required=True, help="output figures JSON")
    b.add_argument("--offset-sagitta", type=float, default=0.01, metavar="M",
                   help="chord sagitta (m) used when baking offset figures "
                        "(default 0.01)")
    b.add_argument("--chord-sagitta", type=float, default=0.01, metavar="M",
                   help="informational: arcs are chorded downstream at this "
                        "sagitta by the adapters (default 0.01)")
    b.add_argument("--strict", action="store_true",
                   help="exit 2 when the build produces any flags")
    b.set_defaults(func=_cmd_build)

    for name, help_text in (
            ("keys-template", "print a documented description-keys starter"),
            ("codeset-template", "print a documented code-set starter"),
            ("prefixes-template", "print a documented figure-prefix starter")):
        t = sub.add_parser(name, help=help_text)
        if name == "codeset-template":
            t.add_argument("--preset", choices=["emlid", "civil3d"],
                           default="emlid")
        t.set_defaults(func=_cmd_template)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LineworkError as exc:  # last-resort guard
        print(f"linework: error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
