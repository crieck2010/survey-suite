"""Figure prefix database: base-code prefix -> figure behaviour.

Mirrors Civil 3D's *figure prefix database*: each entry names a feature
prefix (``EC``, ``BLDG`` ...), the drafting layer and line style its
figures draw with, and the closure expectation:

    expect_closed        the crew means this figure to close (building,
                         lot); an ended-but-open figure is *flagged*
    auto_close           ending the figure snaps it shut when the last
                         shot lands within closure_tolerance_m of the
                         first; the misclosure is always reported
    closure_tolerance_m  snap/flag tolerance, metres
    allow_numeric_suffix prefix "EC" also claims "EC1", "EC2" (the Emlid
                         crew convention); False means exact match only

Longest prefix wins, so ``E`` and ``EC`` can coexist. The database never
fails a build by itself -- an unmatched base code is an *unknown code*
error at build time (with did-you-mean suggestions), never a silent drop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional

from .errors import PrefixDBError

FORMAT = "survey-linework/figure-prefixes"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FigurePrefix:
    prefix: str
    layer: str = "linework"
    style: str = "solid"
    expect_closed: bool = False
    auto_close: bool = False
    closure_tolerance_m: float = 0.05
    allow_numeric_suffix: bool = True


@dataclass
class FigurePrefixDB:
    prefixes: List[FigurePrefix] = dc_field(default_factory=list)
    case_sensitive: bool = False

    def _norm(self, text: str) -> str:
        return text if self.case_sensitive else text.upper()

    def validate(self) -> "FigurePrefixDB":
        if not isinstance(self.prefixes, list):
            raise PrefixDBError("figure-prefixes: 'prefixes' must be a list")
        seen = set()
        for i, pfx in enumerate(self.prefixes):
            where = f"figure-prefixes entry #{i} ({pfx.prefix!r})"
            if not pfx.prefix or not isinstance(pfx.prefix, str):
                raise PrefixDBError(f"{where}: 'prefix' must be non-empty")
            norm = self._norm(pfx.prefix)
            if norm in seen:
                raise PrefixDBError(
                    f"{where}: duplicate prefix (case-insensitive)")
            seen.add(norm)
            if not pfx.layer or not isinstance(pfx.layer, str):
                raise PrefixDBError(f"{where}: 'layer' must be non-empty")
            if not pfx.style or not isinstance(pfx.style, str):
                raise PrefixDBError(f"{where}: 'style' must be non-empty")
            try:
                tol = float(pfx.closure_tolerance_m)
            except (TypeError, ValueError) as exc:
                raise PrefixDBError(
                    f"{where}: 'closure_tolerance_m' must be a number") from exc
            if tol < 0:
                raise PrefixDBError(
                    f"{where}: 'closure_tolerance_m' must be >= 0")
        return self

    def match(self, base_code: str) -> Optional[FigurePrefix]:
        """Longest-prefix match, or None when nothing claims the base code."""
        norm = self._norm(base_code)
        best: Optional[FigurePrefix] = None
        best_len = -1
        for pfx in self.prefixes:
            pn = self._norm(pfx.prefix)
            if norm == pn:
                hit = True
            elif (pfx.allow_numeric_suffix and norm.startswith(pn)
                  and norm[len(pn):].isdigit()):
                hit = True
            else:
                hit = False
            if hit and len(pn) > best_len:
                best = pfx
                best_len = len(pn)
        return best

    def known_prefixes(self) -> List[str]:
        return [p.prefix for p in self.prefixes]

    @classmethod
    def from_dict(cls, data: Dict) -> "FigurePrefixDB":
        if not isinstance(data, dict):
            raise PrefixDBError("figure-prefixes: top-level JSON must be an object")
        if data.get("format") != FORMAT:
            raise PrefixDBError(
                f"figure-prefixes: not a figure-prefix database "
                f"(format={data.get('format')!r}; expected {FORMAT!r})")
        version = data.get("schema_version", 1)
        if version > SCHEMA_VERSION:
            raise PrefixDBError(
                f"figure-prefixes schema v{version} is newer than this reader "
                f"(v{SCHEMA_VERSION}); upgrade survey-linework")
        prefixes = []
        for i, pd in enumerate(data.get("prefixes", [])):
            if not isinstance(pd, dict):
                raise PrefixDBError(
                    f"figure-prefixes entry #{i}: must be an object")
            prefixes.append(FigurePrefix(
                prefix=str(pd.get("prefix", "")),
                layer=str(pd.get("layer", "linework")),
                style=str(pd.get("style", "solid")),
                expect_closed=bool(pd.get("expect_closed", False)),
                auto_close=bool(pd.get("auto_close", False)),
                closure_tolerance_m=float(pd.get("closure_tolerance_m", 0.05)),
                allow_numeric_suffix=bool(pd.get("allow_numeric_suffix", True)),
            ))
        return cls(prefixes=prefixes,
                   case_sensitive=bool(data.get("case_sensitive", False))).validate()

    def to_dict(self) -> Dict:
        return {
            "format": FORMAT,
            "schema_version": SCHEMA_VERSION,
            "case_sensitive": self.case_sensitive,
            "prefixes": [
                {"prefix": p.prefix, "layer": p.layer, "style": p.style,
                 "expect_closed": p.expect_closed, "auto_close": p.auto_close,
                 "closure_tolerance_m": p.closure_tolerance_m,
                 "allow_numeric_suffix": p.allow_numeric_suffix}
                for p in self.prefixes
            ],
        }


def load_prefixes(path: str) -> FigurePrefixDB:
    """Read and validate a figure-prefix JSON file (fail loud)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise PrefixDBError(f"figure-prefixes {path}: cannot read: {exc}") from exc
    try:
        return FigurePrefixDB.from_dict(data)
    except PrefixDBError as exc:
        raise PrefixDBError(f"figure-prefixes {path}: {exc}") from exc


def prefixes_template() -> Dict:
    """Documented starter figure-prefix database."""
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "case_sensitive": False,
        "_about": (
            "Figure prefix database: longest prefix wins; prefix 'EC' with "
            "allow_numeric_suffix claims EC, EC1, EC2 ... expect_closed "
            "flags figures that end open; auto_close snaps the figure shut "
            "when the last shot lands within closure_tolerance_m of the first."
        ),
        "prefixes": [
            {"prefix": "EC", "layer": "linework", "style": "solid",
             "expect_closed": False, "auto_close": False,
             "closure_tolerance_m": 0.05, "allow_numeric_suffix": True},
            {"prefix": "EP", "layer": "linework", "style": "solid",
             "expect_closed": False, "auto_close": False,
             "closure_tolerance_m": 0.05, "allow_numeric_suffix": True},
            {"prefix": "CL", "layer": "linework", "style": "dashed",
             "expect_closed": False, "auto_close": False,
             "closure_tolerance_m": 0.05, "allow_numeric_suffix": True},
            {"prefix": "BLDG", "layer": "linework", "style": "solid",
             "expect_closed": True, "auto_close": True,
             "closure_tolerance_m": 0.10, "allow_numeric_suffix": True},
            {"prefix": "EAS", "layer": "easements", "style": "dashdot",
             "expect_closed": True, "auto_close": True,
             "closure_tolerance_m": 0.10, "allow_numeric_suffix": True},
        ],
    }
