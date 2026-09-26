"""SurveySuite project model: the ``.sproj`` manifest.

A project ties the whole field-to-finish chain together:

    Emlid CSVs -> .sfield.json job -> weights.json -> .sadj.json
      + justification report -> parcel.json / style.json
      -> GeoTIFF basemap -> plat/plan/map PDF + manifest

All artifact paths are stored *relative to the project directory* so a
project folder is portable (zip it, move it, open it on another machine).

This module is Tk-free and fully testable.
"""
from __future__ import annotations

import datetime
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

FORMAT = "survey-suite/project"
SCHEMA_VERSION = 1

RECENT_FILE = os.path.join(os.path.expanduser("~"), ".survey-suite",
                           "recent.json")
MAX_RECENT = 12


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


@dataclass
class SurveyProject:
    """In-memory project; call :meth:`save` to persist the manifest."""
    name: str
    root: str                      # absolute project directory
    crs: str = ""
    csv_files: list = field(default_factory=list)
    job_path: str | None = None            # .sfield.json
    weights_path: str | None = None        # weights.json
    sadj_path: str | None = None           # .sadj.json
    report_path: str | None = None         # justification report.md
    adjusted_job_path: str | None = None   # .adjusted.sfield.json
    parcel_path: str | None = None         # parcel.json
    style_path: str | None = None          # style.json
    basemap_path: str | None = None        # GeoTIFF orthomosaic
    basemap_overviews_built: bool = False
    surveyor_name: str = ""
    surveyor_license: str = ""
    surveyor_state: str = ""
    firm: str = ""
    client: str = ""
    deliverables: list = field(default_factory=list)  # manifest dicts
    created_utc: str = ""
    modified_utc: str = ""

    # -- paths ---------------------------------------------------------
    @property
    def sproj_path(self) -> str:
        return os.path.join(self.root, f"{self.name}.sproj")

    def resolve(self, rel: str | None) -> str | None:
        """Absolute path for a project-relative artifact path."""
        if not rel:
            return None
        p = os.path.join(self.root, rel)
        return os.path.normpath(p)

    def relpath(self, abs_path: str) -> str:
        """Store an absolute path as project-relative (portability)."""
        return os.path.relpath(os.path.abspath(abs_path),
                               os.path.abspath(self.root))

    def set_artifact(self, attr: str, abs_path: str | None) -> None:
        setattr(self, attr, self.relpath(abs_path) if abs_path else None)
        self.touch()

    def artifact_exists(self, attr: str) -> bool:
        rel = getattr(self, attr)
        if not rel:
            return False
        return os.path.isfile(self.resolve(rel))

    def touch(self) -> None:
        self.modified_utc = _utcnow()

    # -- persistence ---------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["format"] = FORMAT
        d["schema_version"] = SCHEMA_VERSION
        d["generator"] = f"survey-suite {__version__()}"
        return d

    def save(self) -> str:
        """Write the manifest; returns the .sproj path."""
        self.touch()
        if not self.created_utc:
            self.created_utc = self.modified_utc
        os.makedirs(self.root, exist_ok=True)
        with open(self.sproj_path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        remember_project(self.sproj_path)
        return self.sproj_path

    @classmethod
    def load(cls, sproj_path: str) -> "SurveyProject":
        with open(sproj_path, encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("format") != FORMAT:
            raise ValueError(f"not a SurveySuite project file: {sproj_path}")
        if d.get("schema_version", 0) > SCHEMA_VERSION:
            raise ValueError(
                f"project schema v{d.get('schema_version')} is newer than "
                f"this app supports (v{SCHEMA_VERSION}); update SurveySuite.")
        d.pop("format", None)
        d.pop("schema_version", None)
        d.pop("generator", None)
        root = os.path.dirname(os.path.abspath(sproj_path))
        d["root"] = root
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def new(cls, name: str, directory: str,
            crs: str = "") -> "SurveyProject":
        now = _utcnow()
        return cls(name=name, root=os.path.abspath(directory), crs=crs,
                   created_utc=now, modified_utc=now)


def __version__() -> str:
    from suite import __version__ as v
    return v


# -- recent projects ----------------------------------------------------

def recent_projects() -> list[str]:
    """Most-recent .sproj paths, newest first; prunes missing files."""
    try:
        with open(RECENT_FILE, encoding="utf-8") as fh:
            paths = json.load(fh)
    except (OSError, ValueError):
        return []
    live = [p for p in paths if os.path.isfile(p)]
    if len(live) != len(paths):
        _write_recent(live)
    return live


def _write_recent(paths: list[str]) -> None:
    os.makedirs(os.path.dirname(RECENT_FILE), exist_ok=True)
    with open(RECENT_FILE, "w", encoding="utf-8") as fh:
        json.dump(paths[:MAX_RECENT], fh, indent=2)


def remember_project(sproj_path: str) -> None:
    paths = [p for p in recent_projects() if p != sproj_path]
    _write_recent([sproj_path] + paths)
