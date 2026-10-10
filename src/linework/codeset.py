"""Linework code sets: the control-token vocabulary of the field crew.

A code set maps raw field codes like ``EC1 *bl`` into *base code* + *control
tokens*. The default ``emlid`` preset follows the convention real Emlid
field crews use (space separator, ``*bl`` begin line / ``*el`` end line, as
documented on the Emlid Community Forum); the ``civil3d`` preset mirrors
Civil 3D's classic BEG/BCV/ECV/END/CLS vocabulary. Every token is
remappable -- invalid configs fail loud naming the exact problem.

Control tokens and what they do (see docs/CODING.md for the field guide):

    begin               start a new figure strand for the base code
    continue            explicit continue (asserts a strand is open)
    end                 end the open strand for the base code
    begin_curve_3pt     start a three-point arc at this vertex
    end_curve_3pt       end the three-point arc at this vertex
    begin_curve_radius  start a radius arc at this vertex (needs R= param)
    end_curve_radius    end the radius arc at this vertex
    close               close the figure back to its first vertex (implies end)
    offset              mark the figure for a parallel offset copy (needs distance)

Parameters ride on the control field after ``:`` or ``=``, or in the next
field: ``EC1 *bcr R=50``, ``EC1 *bcr:R=50``, ``CL *off R2.0``,
``CL *off:+2.0``. Radius also accepts a bare number (``*bcr 50``).
Offset accepts ``+d``/``-d`` (right/left of travel), ``R``/``L`` + distance,
or a bare distance (positive = right of travel).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional, Tuple

from .errors import CodeSetError

FORMAT = "survey-linework/codeset"
SCHEMA_VERSION = 1

# Canonical control kinds, in the order they are applied when several
# ride on one coded point.
KINDS = (
    "begin",
    "continue",
    "end",
    "begin_curve_3pt",
    "end_curve_3pt",
    "begin_curve_radius",
    "end_curve_radius",
    "close",
    "offset",
)

# Kinds that REQUIRE an already-open figure strand (their absence raises
# the fail-loud "X-without-begin" errors). Note the curve *begins* are
# NOT here: like a plain code, they implicitly begin the figure when
# the code set's auto_begin is on (Civil 3D's automatic linework treats
# the BCV shot as the figure's first point).
NEEDS_OPEN = {
    "continue": "continue-without-begin",
    "end": "end-without-begin",
    "end_curve_3pt": "end-curve-without-begin",
    "end_curve_radius": "end-curve-without-begin",
    "close": "close-without-begin",
    "offset": "offset-without-begin",
}

_PARAM_SPLIT = re.compile(r"\s*[:=]\s*")
_RADIUS_RE = re.compile(r"^[Rr]\s*=\s*(\d+(?:\.\d+)?)\s*$")
_BARE_NUMBER_RE = re.compile(r"^([+-]?)(\d+(?:\.\d+)?)\s*$")
_OFFSET_RL_RE = re.compile(r"^([RrLl])\s*(\d+(?:\.\d+)?)\s*$")


def _builtin_emlid() -> Dict:
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "name": "emlid",
        "version": "1.0",
        # Field-verified tokens (Emlid Community Forum, working crews):
        # "<BASE> *bl" begins a line, "<BASE> *el" ends it, space-separated.
        # The curve/close/offset tokens are survey-linework preset extensions
        # in the same "*xx" style -- remap them to your crew's habit.
        "description": (
            "Default Emlid-Flow field convention. begin/end (*bl/*el) follow "
            "the convention Emlid field crews actually use (space separator). "
            "Curve, close and offset tokens are preset extensions in the same "
            "*xx style; remap freely."
        ),
        "separator": " ",
        "case_sensitive": False,
        "auto_begin": True,
        "tokens": {
            "begin": "*bl",
            "continue": "*c",
            "end": "*el",
            "begin_curve_3pt": "*bc3",
            "end_curve_3pt": "*ec3",
            "begin_curve_radius": "*bcr",
            "end_curve_radius": "*ecr",
            "close": "*cl",
            "offset": "*off",
        },
    }


def _builtin_civil3d() -> Dict:
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "name": "civil3d",
        "version": "1.0",
        "description": (
            "Civil 3D-flavoured vocabulary: BEG/END, BCV/ECV three-point "
            "curves, CLS close. BCVR/ECVR (radius curves) and OFF (offset) "
            "are survey-linework preset extensions; remap to your C3D set."
        ),
        "separator": " ",
        "case_sensitive": False,
        "auto_begin": True,
        "tokens": {
            "begin": "BEG",
            "continue": "C",
            "end": "END",
            "begin_curve_3pt": "BCV",
            "end_curve_3pt": "ECV",
            "begin_curve_radius": "BCVR",
            "end_curve_radius": "ECVR",
            "close": "CLS",
            "offset": "OFF",
        },
    }


BUILTIN_PRESETS = {"emlid": _builtin_emlid, "civil3d": _builtin_civil3d}


@dataclass(frozen=True)
class ParsedControl:
    """One control token found on a coded point."""

    kind: str          # one of KINDS
    token: str         # the matched token text (normalised case)
    param: str = ""    # raw parameter text after the token ("" when none)


@dataclass(frozen=True)
class ParsedCode:
    """A raw field code split into base code + control tokens."""

    base: str                       # normalised base code (figure identity)
    controls: Tuple[ParsedControl, ...] = ()


@dataclass
class LineworkCodeSet:
    """Validated, ready-to-use linework code set."""

    name: str = "emlid"
    version: str = "1.0"
    description: str = ""
    separator: str = " "
    case_sensitive: bool = False
    auto_begin: bool = True
    tokens: Dict[str, str] = dc_field(default_factory=dict)

    # -- derived, built by validate() -------------------------------------
    _token_list: List[Tuple[str, str]] = dc_field(default_factory=list,
                                                 repr=False)

    def _norm(self, text: str) -> str:
        return text if self.case_sensitive else text.upper()

    def validate(self) -> "LineworkCodeSet":
        """Check the whole config; raise CodeSetError naming the problem."""
        if not isinstance(self.separator, str) or not self.separator:
            raise CodeSetError("codeset: 'separator' must be a non-empty string")
        if not isinstance(self.tokens, dict):
            raise CodeSetError("codeset: 'tokens' must be an object")
        missing = [k for k in KINDS if k not in self.tokens]
        if missing:
            raise CodeSetError(
                f"codeset '{self.name}': missing control token(s): "
                + ", ".join(missing))
        extra = [k for k in self.tokens if k not in KINDS]
        if extra:
            raise CodeSetError(
                f"codeset '{self.name}': unknown control kind(s): "
                + ", ".join(extra) + f" (known: {', '.join(KINDS)})")
        seen: Dict[str, str] = {}
        for kind in KINDS:
            tok = self.tokens[kind]
            if not isinstance(tok, str) or not tok.strip():
                raise CodeSetError(
                    f"codeset '{self.name}': token for '{kind}' must be a "
                    "non-empty string")
            norm = self._norm(tok.strip())
            if norm in seen:
                raise CodeSetError(
                    f"codeset '{self.name}': tokens for '{seen[norm]}' and "
                    f"'{kind}' both normalise to {norm!r}; control tokens "
                    "must be distinct")
            seen[norm] = kind
        # Longest token first so "*bcr" wins over "*b" style prefixes.
        self._token_list = sorted(
            ((self._norm(t.strip()), kind) for kind, t in self.tokens.items()
             if kind in KINDS),
            key=lambda kv: -len(kv[0]))
        return self

    # -- parsing -----------------------------------------------------------
    def _match_token(self, field_text: str) -> Optional[Tuple[str, str, str]]:
        """Match a raw field against control tokens.

        Returns (kind, token, param_remainder) or None.
        """
        norm = self._norm(field_text.strip())
        for token, kind in self._token_list:
            if norm == token or norm.startswith(token):
                rest = field_text.strip()[len(token):]
                param = _PARAM_SPLIT.sub("", rest, count=1).strip() \
                    if rest[:1] in ":=" else rest.strip()
                # A bare token followed by junk that is not a : or = split
                # (e.g. "*blx") is NOT a match -- keep looking.
                if rest and rest[:1] not in ":=" and rest.strip():
                    # Allow "*bcrR=50" style glued params only when the rest
                    # parses as a parameter; otherwise not a token match.
                    if not self._looks_like_param(kind, rest.strip()):
                        continue
                    param = rest.strip()
                return kind, token, param
        return None

    @staticmethod
    def _looks_like_param(kind: str, text: str) -> bool:
        if kind in ("begin_curve_radius",):
            return bool(_RADIUS_RE.match(text) or _BARE_NUMBER_RE.match(text))
        if kind == "offset":
            return bool(_OFFSET_RL_RE.match(text)
                        or _BARE_NUMBER_RE.match(text))
        return False

    def parse_code(self, raw: str) -> ParsedCode:
        """Split a raw field code into base code + control tokens.

        Raises CodeSetError on an unrecognised control field (fail loud --
        a mistyped token must never be silently ignored).
        """
        raw = (raw or "")
        if not raw.strip():
            raise CodeSetError("parse_code: empty raw code")
        fields = [f for f in raw.split(self.separator) if f.strip()]
        if not fields:
            raise CodeSetError(f"parse_code: code {raw!r} has no base field")
        base = self._norm(fields[0].strip())
        controls: List[ParsedControl] = []
        i = 1
        while i < len(fields):
            matched = self._match_token(fields[i])
            if matched is None:
                # Maybe a bare parameter belonging to the previous control
                # ("EC1 *bcr R=50", "CL *off +2.0").
                if controls and self._looks_like_param(
                        controls[-1].kind, fields[i].strip()):
                    prev = controls[-1]
                    controls[-1] = ParsedControl(prev.kind, prev.token,
                                                fields[i].strip())
                    i += 1
                    continue
                known = ", ".join(t for t, _ in self._token_list)
                raise CodeSetError(
                    f"unrecognised control field {fields[i]!r} in code "
                    f"{raw!r} (base {base!r}); known tokens: {known}. "
                    "Fix the field code or remap the code set.")
            kind, token, param = matched
            controls.append(ParsedControl(kind, token, param))
            i += 1
        # Deterministic application order regardless of field order.
        order = {k: n for n, k in enumerate(KINDS)}
        controls.sort(key=lambda c: order[c.kind])
        return ParsedCode(base=base, controls=tuple(controls))

    # -- parameter interpretation ------------------------------------------
    @staticmethod
    def radius_param(param: str, raw: str) -> float:
        """Interpret a radius parameter; fail loud on garbage."""
        m = _RADIUS_RE.match(param or "")
        if m:
            return float(m.group(1))
        m = _BARE_NUMBER_RE.match(param or "")
        if m and m.group(1) in ("", "+"):
            return float(m.group(2))
        raise CodeSetError(
            f"bad radius parameter {param!r} in code {raw!r}; "
            "use R=<metres>, e.g. '*bcr R=50'")

    @staticmethod
    def offset_param(param: str, raw: str) -> float:
        """Interpret an offset parameter.

        Positive = right of travel, negative = left. Accepts +d / -d,
        R<dist> / L<dist>, or a bare distance (positive).
        """
        m = _OFFSET_RL_RE.match(param or "")
        if m:
            dist = float(m.group(2))
            return dist if m.group(1).upper() == "R" else -dist
        m = _BARE_NUMBER_RE.match(param or "")
        if m:
            dist = float(m.group(2))
            return -dist if m.group(1) == "-" else dist
        raise CodeSetError(
            f"bad offset parameter {param!r} in code {raw!r}; "
            "use +<d>/-<d>, R<d>/L<d>, e.g. '*off +0.6'")

    # -- construction --------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Dict) -> "LineworkCodeSet":
        if not isinstance(data, dict):
            raise CodeSetError("codeset: top-level JSON must be an object")
        if data.get("format") != FORMAT:
            raise CodeSetError(
                f"codeset: not a linework code set (format={data.get('format')!r}; "
                f"expected {FORMAT!r})")
        version = data.get("schema_version", 1)
        if version > SCHEMA_VERSION:
            raise CodeSetError(
                f"codeset schema v{version} is newer than this reader "
                f"(v{SCHEMA_VERSION}); upgrade survey-linework")
        toks = data.get("tokens", {})
        cs = cls(
            name=str(data.get("name", "unnamed")),
            version=str(data.get("version", "1.0")),
            description=str(data.get("description", "")),
            separator=data.get("separator", " "),
            case_sensitive=bool(data.get("case_sensitive", False)),
            auto_begin=bool(data.get("auto_begin", True)),
            tokens={k: str(v) for k, v in toks.items()},
        )
        return cs.validate()

    def to_dict(self) -> Dict:
        return {
            "format": FORMAT,
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "separator": self.separator,
            "case_sensitive": self.case_sensitive,
            "auto_begin": self.auto_begin,
            "tokens": dict(self.tokens),
        }


def load_codeset(path: str) -> LineworkCodeSet:
    """Read and validate a code-set JSON file (fail loud)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise CodeSetError(f"codeset {path}: cannot read: {exc}") from exc
    try:
        return LineworkCodeSet.from_dict(data)
    except CodeSetError as exc:
        raise CodeSetError(f"codeset {path}: {exc}") from exc


def codeset_template(preset: str = "emlid") -> Dict:
    """Return the documented starter code set for a preset."""
    try:
        maker = BUILTIN_PRESETS[preset]
    except KeyError:
        raise CodeSetError(
            f"unknown codeset preset {preset!r}; "
            f"known: {', '.join(sorted(BUILTIN_PRESETS))}") from None
    return maker()


def builtin_codeset(preset: str = "emlid") -> LineworkCodeSet:
    """Load a built-in preset without touching the filesystem."""
    return LineworkCodeSet.from_dict(codeset_template(preset))
