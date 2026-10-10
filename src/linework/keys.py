"""Description keys: raw field code -> point symbology.

A description key maps a raw field code (with ``*``/``?`` wildcards, e.g.
``EP*``) to a drafting layer, a point symbol, and a label format. Keys
apply to *every* coded point -- including points that join no figure --
so a topo shot coded ``TREE`` still lands on the right layer with the
right symbol.

Longest-match wins: among the patterns matching a base code, the longest
pattern string wins; ties resolve in file order (deterministic,
documented). Matching is case-insensitive by default.

Label formats are Python format strings over ``{name}``, ``{code}``,
``{easting}``, ``{northing}``, ``{elevation}``. They are trial-rendered at
load time so a typo fails loud here, not on the thousandth point.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional

from .errors import DescriptionKeyError

FORMAT = "survey-linework/description-keys"
SCHEMA_VERSION = 1

LABEL_FIELDS = ("name", "code", "easting", "northing", "elevation")


@dataclass(frozen=True)
class DescriptionKey:
    pattern: str
    layer: str = "points"
    symbol: str = "circle"
    label: str = "{name}"


@dataclass
class DescriptionKeys:
    """Validated description-key set with longest-match lookup."""

    keys: List[DescriptionKey] = dc_field(default_factory=list)
    default: DescriptionKey = dc_field(
        default_factory=lambda: DescriptionKey("*", "points", "circle", "{name}"))
    case_sensitive: bool = False

    def _norm(self, text: str) -> str:
        return text if self.case_sensitive else text.upper()

    def validate(self) -> "DescriptionKeys":
        if not isinstance(self.keys, list):
            raise DescriptionKeyError("description-keys: 'keys' must be a list")
        seen = set()
        for i, key in enumerate(self.keys):
            where = f"description-keys key #{i} ({key.pattern!r})"
            if not key.pattern or not isinstance(key.pattern, str):
                raise DescriptionKeyError(f"{where}: 'pattern' must be non-empty")
            norm = self._norm(key.pattern)
            if norm in seen:
                raise DescriptionKeyError(
                    f"{where}: duplicate pattern (case-insensitive); "
                    "each pattern may appear once")
            seen.add(norm)
            if not key.layer or not isinstance(key.layer, str):
                raise DescriptionKeyError(f"{where}: 'layer' must be non-empty")
            if not key.symbol or not isinstance(key.symbol, str):
                raise DescriptionKeyError(f"{where}: 'symbol' must be non-empty")
            self._check_label(key.label, where)
        self._check_label(self.default.label, "description-keys 'default'")
        return self

    @staticmethod
    def _check_label(label: str, where: str) -> None:
        if not isinstance(label, str):
            raise DescriptionKeyError(f"{where}: 'label' must be a string")
        probe = {f: f"<{f}>" for f in LABEL_FIELDS}
        try:
            label.format(**probe)
        except (KeyError, IndexError, ValueError) as exc:
            raise DescriptionKeyError(
                f"{where}: bad label format {label!r}: {exc}; "
                f"allowed fields: {', '.join('{'+f+'}' for f in LABEL_FIELDS)}"
            ) from exc

    def match(self, base_code: str) -> DescriptionKey:
        """Longest-match lookup; ties resolve in file order."""
        norm = self._norm(base_code)
        best: Optional[DescriptionKey] = None
        best_len = -1
        for key in self.keys:
            if fnmatch.fnmatchcase(norm, self._norm(key.pattern)):
                if len(key.pattern) > best_len:
                    best = key
                    best_len = len(key.pattern)
        return best if best is not None else self.default

    def render_label(self, key: DescriptionKey, point: Dict) -> str:
        probe = {
            "name": str(point.get("name", "")),
            "code": str(point.get("code", "")),
            "easting": point.get("easting"),
            "northing": point.get("northing"),
            "elevation": point.get("elevation"),
        }
        try:
            return key.label.format(**probe)
        except (KeyError, IndexError, ValueError) as exc:
            raise DescriptionKeyError(
                f"label render failed for pattern {key.pattern!r}: {exc}"
            ) from exc

    @classmethod
    def from_dict(cls, data: Dict) -> "DescriptionKeys":
        if not isinstance(data, dict):
            raise DescriptionKeyError("description-keys: top-level JSON must be an object")
        if data.get("format") != FORMAT:
            raise DescriptionKeyError(
                f"description-keys: not a description-key set "
                f"(format={data.get('format')!r}; expected {FORMAT!r})")
        version = data.get("schema_version", 1)
        if version > SCHEMA_VERSION:
            raise DescriptionKeyError(
                f"description-keys schema v{version} is newer than this reader "
                f"(v{SCHEMA_VERSION}); upgrade survey-linework")
        case_sensitive = bool(data.get("case_sensitive", False))
        dflt = data.get("default", {})
        default = DescriptionKey(
            pattern="*",
            layer=str(dflt.get("layer", "points")),
            symbol=str(dflt.get("symbol", "circle")),
            label=str(dflt.get("label", "{name}")),
        )
        keys = []
        for i, kd in enumerate(data.get("keys", [])):
            if not isinstance(kd, dict):
                raise DescriptionKeyError(
                    f"description-keys key #{i}: must be an object")
            keys.append(DescriptionKey(
                pattern=str(kd.get("pattern", "")),
                layer=str(kd.get("layer", "points")),
                symbol=str(kd.get("symbol", "circle")),
                label=str(kd.get("label", "{name}")),
            ))
        return cls(keys=keys, default=default,
                   case_sensitive=case_sensitive).validate()

    def to_dict(self) -> Dict:
        return {
            "format": FORMAT,
            "schema_version": SCHEMA_VERSION,
            "case_sensitive": self.case_sensitive,
            "default": {
                "layer": self.default.layer,
                "symbol": self.default.symbol,
                "label": self.default.label,
            },
            "keys": [
                {"pattern": k.pattern, "layer": k.layer,
                 "symbol": k.symbol, "label": k.label}
                for k in self.keys
            ],
        }


def load_keys(path: str) -> DescriptionKeys:
    """Read and validate a description-keys JSON file (fail loud)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise DescriptionKeyError(f"description-keys {path}: cannot read: {exc}") from exc
    try:
        return DescriptionKeys.from_dict(data)
    except DescriptionKeyError as exc:
        raise DescriptionKeyError(f"description-keys {path}: {exc}") from exc


def keys_template() -> Dict:
    """Documented starter description-key set."""
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "case_sensitive": False,
        "_about": (
            "Description keys map field codes (wildcards * ?) to drafting "
            "layer, point symbol and label. Longest pattern wins; ties use "
            "file order. Labels use {name} {code} {easting} {northing} "
            "{elevation}. Points with an empty code always get 'default'."
        ),
        "default": {"layer": "points", "symbol": "circle", "label": "{name}"},
        "keys": [
            {"pattern": "EC*", "layer": "linework", "symbol": "square",
             "label": "{name}"},
            {"pattern": "EP*", "layer": "linework", "symbol": "square",
             "label": "{name}"},
            {"pattern": "BLDG*", "layer": "linework", "symbol": "triangle",
             "label": "{name}"},
            {"pattern": "CL*", "layer": "linework", "symbol": "cross",
             "label": "{name} CL"},
            {"pattern": "MH*", "layer": "linework", "symbol": "circle",
             "label": "{name} MH"},
            {"pattern": "TREE*", "layer": "points", "symbol": "circle",
             "label": "{name} TREE"},
            {"pattern": "BM*", "layer": "control", "symbol": "triangle",
             "label": "{name} BM {elevation}"},
        ],
    }
