"""RINEX observation-file header parsing for survey-opus.

Pure-stdlib engine: reads the headers of RINEX 2.x / 3.x observation files
(stops at ``END OF HEADER`` -- observation records are never touched) and
checks them against NOAA OPUS submission requirements.

Nothing in this module imports a UI framework or any third-party package.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path

__all__ = ["RinexError", "RinexHeader", "parse_header", "validate_for_opus"]

#: OPUS rapid-static minimum session length, minutes.
_RAPID_STATIC_MIN_MIN = 15.0
#: OPUS static minimum session length, hours.
_STATIC_MIN_HOURS = 2.0

#: Antenna-type strings that are obviously placeholders, not real NGS codes
#: (the NGS antenna list's first entry is ``NONE``).
_PLACEHOLDER_ANTENNAS = {"", "NONE", "UNKNOWN", "N/A", "NA", "NULL", "?"}


class RinexError(ValueError):
    """Raised when a RINEX observation-file header cannot be parsed."""


@dataclasses.dataclass
class RinexHeader:
    """Parsed contents of a RINEX 2.x / 3.x observation-file header.

    ``end_time`` is ``None`` when the header has no ``TIME OF LAST OBS``
    line, and ``approx_position`` is ``None`` when ``APPROX POSITION XYZ``
    is absent -- both are optional in the file, so they are not parse
    errors; :func:`validate_for_opus` flags them instead.
    """

    rinex_version: str  # "2.11" / "3.04" ...
    marker_name: str
    antenna_type: str  # from ANT # / TYPE header
    antenna_height: float  # meters (ANTENNA: DELTA H/E/N -> H)
    approx_position: tuple[float, float, float] | None  # XYZ ECEF meters
    start_time: datetime  # TIME OF FIRST OBS (naive; file's stated time system)
    end_time: datetime | None  # TIME OF LAST OBS (may be absent)
    constellations: set[str]  # {"G","R","E","C","J",...}
    # Per-constellation obs codes (RINEX 3 SYS / # / OBS TYPES). RINEX 2
    # lists observation types once for the whole file, so the dict carries
    # a single entry keyed by the version line's satellite system ("G", "R",
    # "E", or "M" -- "G" when the field is blank).
    obs_types: dict[str, list[str]]
    interval: float | None  # seconds between epochs


def _label(line: str) -> str:
    """Return the header label occupying columns 61-80 of a header line."""
    return line[60:80].strip()


def _is_number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def _parse_epoch(tokens: list[str], path: Path, what: str) -> datetime:
    """Build a datetime from the numeric fields of a TIME OF ... OBS line.

    RINEX 3 appends a time-system tag (GPS/UTC/GLO/...) after the seconds;
    it is accepted and ignored -- the returned datetime is naive, expressed
    in the file's stated time system.
    """
    if len(tokens) < 6:
        raise RinexError(f"malformed {what} in {path}: {' '.join(tokens)!r}")
    try:
        year, month, day, hour, minute = (int(t) for t in tokens[0:5])
        sec = float(tokens[5])
    except ValueError:
        raise RinexError(f"malformed {what} in {path}: {' '.join(tokens)!r}") from None
    if year < 100:
        # RINEX 2 two-digit-year convention: 80-99 -> 1980-1999, else 2000s.
        year += 2000 if year < 80 else 1900
    whole = int(sec)
    micro = int(round((sec - whole) * 1_000_000))
    if micro == 1_000_000:
        whole += 1
        micro = 0
    try:
        return datetime(year, month, day, hour, minute, whole, micro)
    except ValueError as exc:
        raise RinexError(f"malformed {what} in {path}: {exc}") from None


def _epoch_from_line(line: str, path: Path, what: str) -> datetime:
    """Parse a TIME OF FIRST/LAST OBS header line (RINEX 2.x and 3.x)."""
    tokens = line[:60].split()
    # Drop a trailing non-numeric time-system tag (GPS/UTC/GLO/...).
    if tokens and not _is_number(tokens[-1]) and len(tokens) > 6:
        tokens = tokens[:-1]
    return _parse_epoch(tokens, path, what)


def _rinex2_obs_types(line: str, pending: list[int]) -> list[str]:
    """Extract obs codes from a RINEX 2 '# / TYPES OF OBSERV' line.

    Format is ``I6, 9(4X,A2)``: the count lives in columns 1-6 and up to
    nine 2-char codes start at column 11. ``pending`` is a one-element list
    used to carry the remaining expected count across continuation lines.
    """
    count_str = line[0:6].strip()
    if count_str:
        try:
            pending[0] = int(count_str)
        except ValueError:
            pending[0] = 0
    codes = []
    for i in range(9):
        if pending[0] <= 0:
            break
        code = line[10 + 6 * i : 12 + 6 * i].strip()
        if code:
            codes.append(code)
        pending[0] -= 1
    return codes


def _rinex3_sys_types(line: str, offset: int, pending: list[int]) -> list[str]:
    """Extract obs codes from a RINEX 3 'SYS / # / OBS TYPES' line.

    Format is ``A1,1X,I3,3X,13(4-char codes)``; continuation lines use a
    6-space prefix. ``offset`` is 7 for the first line of a system block
    and 6 for continuations.
    """
    codes = []
    for i in range(13):
        if pending[0] <= 0:
            break
        code = line[offset + 4 * i : offset + 4 * i + 4].strip()
        if code:
            codes.append(code)
        pending[0] -= 1
    return codes


def parse_header(path: str | Path) -> RinexHeader:
    """Parse the header of a RINEX 2.x / 3.x observation file.

    Only header lines are read; parsing stops at ``END OF HEADER``.

    Raises:
        RinexError: if the file is missing/unreadable, is not a RINEX
            observation file (bad first line), carries an unparseable or
            unsupported version, has a truncated header (no END OF
            HEADER), lacks MARKER NAME, or lacks TIME OF FIRST OBS.
            Missing *optional* fields (antenna height, approx position,
            TIME OF LAST OBS, INTERVAL) are not errors -- they come back
            as ``0.0`` / ``None`` and :func:`validate_for_opus` reports
            the ones OPUS needs.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RinexError(f"RINEX file not found or unreadable: {path}") from exc

    lines = text.splitlines()
    if not lines:
        raise RinexError(f"not a RINEX observation file: {path} (empty file)")

    first = lines[0]
    # File type is the single character at column 21 ('O' = observation);
    # real RINEX files do not spell out "OBSERVATION" on this line.
    file_type = first[20] if len(first) > 20 else ""
    if _label(first) != "RINEX VERSION / TYPE" or file_type != "O":
        raise RinexError(
            f"not a RINEX observation file: {path} "
            f"(bad first line: {first[:60].rstrip()!r})"
        )
    ver_str = first[0:9].strip()
    try:
        version = float(ver_str)
    except ValueError:
        raise RinexError(f"unparseable RINEX version {ver_str!r} in {path}") from None
    major = int(version)
    if major not in (2, 3):
        raise RinexError(
            f"unsupported RINEX version {ver_str!r} in {path}; "
            "only 2.x and 3.x observation files are supported"
        )

    rinex2_sys = (first[40] if len(first) > 40 else " ").strip() or "G"

    marker_name = ""
    antenna_type = ""
    antenna_height = 0.0
    approx_position: tuple[float, float, float] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    interval: float | None = None
    constellations: set[str] = set()
    obs_types: dict[str, list[str]] = {}
    seen_end = False

    # State for multi-line obs-type records.
    pending2 = [0]  # RINEX 2 remaining '# / TYPES OF OBSERV' count
    pending3 = [0]  # RINEX 3 remaining 'SYS / # / OBS TYPES' count
    pending3_sys = ""

    for line in lines[1:]:
        label = _label(line)

        if label == "END OF HEADER":
            seen_end = True
            break

        if label == "MARKER NAME":
            marker_name = line[0:60].strip()
        elif label == "ANT # / TYPE":
            antenna_type = line[20:40].strip()
        elif label == "ANTENNA: DELTA H/E/N":
            try:
                antenna_height = float(line[0:14].strip())
            except ValueError:
                antenna_height = 0.0
        elif label == "APPROX POSITION XYZ":
            try:
                approx_position = (
                    float(line[0:14].strip()),
                    float(line[14:28].strip()),
                    float(line[28:42].strip()),
                )
            except ValueError:
                approx_position = None
        elif label == "TIME OF FIRST OBS":
            start_time = _epoch_from_line(line, p, "TIME OF FIRST OBS")
        elif label == "TIME OF LAST OBS":
            end_time = _epoch_from_line(line, p, "TIME OF LAST OBS")
        elif label == "INTERVAL":
            try:
                interval = float(line[0:10].strip())
            except ValueError:
                interval = None
        elif label == "# / TYPES OF OBSERV":
            codes = _rinex2_obs_types(line, pending2)
            obs_types.setdefault(rinex2_sys, []).extend(codes)
        elif label == "SYS / # / OBS TYPES":
            sys = line[0].strip() or "?"
            count_str = line[3:6].strip()
            try:
                pending3[0] = int(count_str)
            except ValueError:
                pending3[0] = 0
            pending3_sys = sys
            constellations.add(sys)
            codes = _rinex3_sys_types(line, 7, pending3)
            obs_types.setdefault(sys, []).extend(codes)
        elif not label:
            # Blank label: possible continuation of an obs-type record.
            if major == 2 and pending2[0] > 0:
                obs_types.setdefault(rinex2_sys, []).extend(
                    _rinex2_obs_types(line, pending2)
                )
            elif major == 3 and pending3[0] > 0 and pending3_sys:
                obs_types.setdefault(pending3_sys, []).extend(
                    _rinex3_sys_types(line, 6, pending3)
                )
            # Otherwise (e.g. LEAP SECONDS update-info lines): ignore.
        # All other labels (LEAP SECONDS, PGM / RUN BY / DATE, COMMENT, ...)
        # are ignored gracefully.

    if not seen_end:
        raise RinexError(f"truncated RINEX header in {path}: no END OF HEADER found")
    if not marker_name:
        raise RinexError(f"missing MARKER NAME in RINEX header: {path}")
    if start_time is None:
        raise RinexError(f"missing TIME OF FIRST OBS in RINEX header: {path}")

    if major == 2:
        if rinex2_sys == "M":
            constellations = {"G", "R", "E"}
        else:
            constellations = {rinex2_sys}

    return RinexHeader(
        rinex_version=ver_str,
        marker_name=marker_name,
        antenna_type=antenna_type,
        antenna_height=antenna_height,
        approx_position=approx_position,
        start_time=start_time,
        end_time=end_time,
        constellations=constellations,
        obs_types=obs_types,
        interval=interval,
    )


def _fmt_span(start: datetime, end: datetime) -> str:
    minutes = (end - start).total_seconds() / 60.0
    if minutes < 60:
        return f"{minutes:.0f} min"
    return f"{minutes / 60:.1f} h"


def validate_for_opus(header: RinexHeader) -> list[str]:
    """Check a parsed RINEX header against OPUS submission requirements.

    Returns a list of problem strings; an empty list means the file is
    submittable. Entries prefixed ``WARN:`` are advisories, not blockers
    (session shorter than the 2 h OPUS-static minimum but at/above the
    15 min rapid-static floor).
    """
    problems: list[str] = []

    if not header.marker_name or not header.marker_name.strip():
        problems.append("marker name is missing; OPUS requires MARKER NAME")

    ant = (header.antenna_type or "").strip()
    if ant.upper() in _PLACEHOLDER_ANTENNAS:
        problems.append(
            f"antenna type missing or placeholder ({header.antenna_type!r}); "
            "OPUS requires a real NGS antenna code"
        )

    if header.antenna_height <= 0:
        problems.append(
            f"antenna height is {header.antenna_height} m; "
            "OPUS requires antenna type and height > 0"
        )

    if header.end_time is None:
        problems.append(
            "TIME OF LAST OBS is missing; cannot verify observation span "
            "(OPUS static needs >= 2 h)"
        )
    else:
        minutes = (header.end_time - header.start_time).total_seconds() / 60.0
        if minutes < _RAPID_STATIC_MIN_MIN:
            problems.append(
                f"observation span is {_fmt_span(header.start_time, header.end_time)} "
                "(< 15 min); below the OPUS rapid-static minimum"
            )
        elif minutes < _STATIC_MIN_HOURS * 60:
            problems.append(
                f"WARN: observation span is {_fmt_span(header.start_time, header.end_time)} "
                "(< 2 h); OPUS static requires 2 h+, rapid-static accepts 15 min-2 h"
            )

    codes = [c.upper() for lst in header.obs_types.values() for c in lst]
    if not any(c.startswith("L2") for c in codes):
        problems.append(
            "no L2 carrier-phase observation types found; "
            "OPUS requires dual-frequency GPS data"
        )

    return problems
