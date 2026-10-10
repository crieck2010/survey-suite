"""Canonical JSON interchange format for field jobs.

A ``.sfield.json`` job file is the contract between survey-field and every
downstream consumer (adjustment workflow, COGO drafting, desktop app):

.. code-block:: json

    {
      "format": "survey-field/job",
      "schema_version": 1,
      "generator": "survey-field 0.2.0",
      "project": { ... Project.to_dict() ... }
    }

When the import ran with ``--target-crs``, the project dict carries an
additional additive ``crs_provenance`` block (schema stays v1; v1 files
simply omit it and still read):

.. code-block:: json

    "crs_provenance": {
      "source_crs": {"name": "WGS 84", "epsg": 4326, "datum": "WGS 84 (G2296)",
                     "unit": "deg", "as_recorded_in_csv": "WGS 84"},
      "target_crs": {"name": "NAD83(2011) / New York Long Island (ftUS)",
                     "epsg": 6539, "datum": "NAD83(2011)", "unit": "ftUS"},
      "transform": {
        "applied": true, "n_points": 3,
        "survey_crs_version": "0.1.0", "backend": "internal",
        "datum_path": {"from_datum": "WGS 84 (G2296)", "to_datum": "NAD83(2011)",
                       "method": "null-approximation", "accuracy_horizontal_m": 2.0,
                       "region": "CONUS", "source": "...", "warning": "..."},
        "warnings": ["datum: Approximate identity shift (<=~2 m horizontal ...)"],
        "timestamp": "2026-09-26T22:31:00+00:00"
      },
      "notes": ["reprojected 3 point(s) from ..."]
    }

Schema changes bump ``schema_version``; readers reject newer versions they do
not understand (fail loud, never misread coordinates).
"""

from __future__ import annotations

import json
from typing import Any, Dict

from . import __version__
from .models import JOB_FORMAT, SCHEMA_VERSION, Project


def dump_job(project: Project) -> Dict[str, Any]:
    return {
        "format": JOB_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "generator": f"survey-field {__version__}",
        "project": project.to_dict(),
    }


def load_job(data: Dict[str, Any]) -> Project:
    if data.get("format") != JOB_FORMAT:
        raise ValueError(
            f"not a survey-field job file (format={data.get('format')!r})")
    version = data.get("schema_version", 0)
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"job schema v{version} is newer than this reader (v{SCHEMA_VERSION}); "
            "upgrade survey-field")
    return Project.from_dict(data["project"])


def write_job(project: Project, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dump_job(project), fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def read_job(path: str) -> Project:
    with open(path, "r", encoding="utf-8") as fh:
        return load_job(json.load(fh))
