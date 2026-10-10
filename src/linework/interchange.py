"""Versioned figures JSON interchange (``survey-linework/figures``, schema v1).

The figures file is the contract between the linework engine and every
downstream consumer (the desktop app's future Figures toolbox,
survey-drafting, survey-cogo). Readers reject ``schema_version`` newer
than they understand -- loudly, never misread.

Envelope::

    {
      "format": "survey-linework/figures",
      "schema_version": 1,
      "generator": "survey-linework 0.1.0",
      "job": {"name": ..., "sha256": ..., "crs": ..., "n_sessions": ...},
      "codeset": {"name": "emlid", "version": "1.0"},
      "figures": [ ...Figure.to_dict()... ],
      "points": [ ...PointRecord.to_dict()... ],
      "report": {"flags": [...], "warnings": [...], "counts": {...}}
    }
"""

from __future__ import annotations

import json
from typing import Any, Dict

from . import __version__
from .errors import InterchangeError
from .figures import BuildResult, Figure

FORMAT = "survey-linework/figures"
SCHEMA_VERSION = 1


def dump_figures(result: BuildResult) -> Dict[str, Any]:
    """Serialize a BuildResult to the interchange dict."""
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "generator": f"survey-linework {__version__}",
        "job": dict(result.job_meta),
        "codeset": dict(result.codeset_meta),
        "figures": [f.to_dict() for f in result.figures],
        "points": [p.to_dict() for p in result.points],
        "report": {
            "flags": list(result.flags),
            "warnings": list(result.warnings),
            "counts": result.counts(),
        },
    }


def write_figures(result: BuildResult, path: str) -> None:
    """Write the interchange JSON to ``path``."""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dump_figures(result), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except OSError as exc:
        raise InterchangeError(f"cannot write figures file {path}: {exc}") from exc


def load_figures(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an interchange dict; reject newer schemas loudly.

    Returns the dict unchanged (figures are consumed as plain dicts, the
    same shape survey-drafting uses for its layer entities).
    """
    if not isinstance(data, dict):
        raise InterchangeError("figures file: top-level JSON must be an object")
    if data.get("format") != FORMAT:
        raise InterchangeError(
            f"not a survey-linework figures file (format={data.get('format')!r}; "
            f"expected {FORMAT!r})")
    version = data.get("schema_version", 0)
    if version > SCHEMA_VERSION:
        raise InterchangeError(
            f"figures schema v{version} is newer than this reader "
            f"(v{SCHEMA_VERSION}); upgrade survey-linework")
    for key in ("figures", "points", "report"):
        if key not in data:
            raise InterchangeError(
                f"figures file: missing required key {key!r}")
    return data


def read_figures(path: str) -> Dict[str, Any]:
    """Read and validate a figures JSON file (fail loud)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise InterchangeError(f"cannot read figures file {path}: {exc}") from exc
    try:
        return load_figures(data)
    except InterchangeError as exc:
        raise InterchangeError(f"figures file {path}: {exc}") from exc


def figures_from_dict(data: Dict[str, Any]) -> list:
    """Rebuild Figure objects from validated interchange data."""
    load_figures(data)
    return [Figure.from_dict(f) for f in data["figures"]]
