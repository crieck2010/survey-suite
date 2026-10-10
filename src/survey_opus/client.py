"""NGS OPUS upload client and solution-report parser.

Pure-logic engine: no UI-framework imports, no third-party requirement.
HTTP uses ``requests`` when importable, otherwise the standard library
(``urllib``) builds the multipart POST by hand. RINEX pre-submit
validation is delegated to the sibling :mod:`survey_opus.rinex` module.

Hard etiquette rule: this module never retries and never submits anything
on its own -- :func:`submit` performs exactly one POST per call, to the
caller-supplied session or to the NGS endpoints above.
"""

from __future__ import annotations

import dataclasses
import datetime
import io
import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import field
from pathlib import Path

from . import rinex

try:  # optional: stdlib urllib multipart is the fallback
    import requests as _requests
except ImportError:  # pragma: no cover - exercised via monkeypatch in tests
    _requests = None

#: NGS OPUS upload endpoints (live-verified 2026-10-08).
OPUS_UPLOAD_URL = "https://www.ngs.noaa.gov/OPUS-cgi/OPUS/Upload/Opusup.prl"
OPUS_RS_UPLOAD_URL = "https://www.ngs.noaa.gov/OPUS-cgi/OPUS/Upload/Opus-rsup.prl"

__all__ = [
    "OPUS_UPLOAD_URL",
    "OPUS_RS_UPLOAD_URL",
    "OpusError",
    "SubmissionReceipt",
    "Coordinate",
    "GridCoordinate",
    "OpusSolution",
    "submit",
    "parse_solution",
    "solution_to_json",
]


class OpusError(Exception):
    """Raised for any OPUS client failure: bad input, RINEX problems, HTTP
    errors, or unparsable solution reports."""


# ---------------------------------------------------------------------------
# submit()
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"
)

#: Characters the NGS upload form rejects in the RINEX filename
#: (per the OPUS upload page validation).
_ILLEGAL_FILENAME_CHARS = frozenset("!@#$%^&*()+=[]{}|;\"'< >?~`-")

_FILENAME_LIMIT = 44


@dataclasses.dataclass
class SubmissionReceipt:
    """Proof of a single OPUS submission attempt."""

    submitted_at: str  # ISO-8601 UTC timestamp of the attempt
    email: str  # lowercased recipient address, as submitted
    rinex_filename: str  # basename of the uploaded file
    antenna_type: str
    antenna_height: float  # meters
    mode: str  # "static" | "rapid-static"
    endpoint_url: str
    seqnum: str  # "OP" + UTC timestamp, sent as the form's seqnum field
    response_status: int  # HTTP status of the single POST attempt
    response_excerpt: str  # first ~500 characters of the response body
    warnings: list[str] = field(default_factory=list)  # WARN: advisories let through


def _validate_email(email: str) -> str:
    address = (email or "").strip()
    if not _EMAIL_RE.match(address):
        raise OpusError(f"invalid email address: {email!r}")
    return address.lower()


def _validate_filename(filename: str) -> None:
    if len(filename) > _FILENAME_LIMIT:
        raise OpusError(
            f"RINEX filename {filename!r} is {len(filename)} characters; "
            f"OPUS accepts at most {_FILENAME_LIMIT}"
        )
    illegal = sorted({c for c in filename if c in _ILLEGAL_FILENAME_CHARS})
    if illegal:
        shown = " ".join(repr(c) for c in illegal)
        raise OpusError(
            f"RINEX filename {filename!r} contains characters OPUS rejects: {shown}"
        )


def _validate_rinex(path: Path) -> list[str]:
    """Parse + OPUS-validate the RINEX header.

    Returns the WARN:-prefixed advisories (allowed through). Raises
    OpusError for parse failures and for hard (non-WARN) problems.
    """
    try:
        header = rinex.parse_header(path)
    except rinex.RinexError as exc:
        raise OpusError(f"RINEX header parse failed: {exc}") from exc
    problems = rinex.validate_for_opus(header) or []
    hard = [p for p in problems if not p.startswith("WARN:")]
    if hard:
        raise OpusError(
            "RINEX file is not submittable to OPUS:\n"
            + "\n".join(f"  - {p}" for p in hard)
        )
    return [p for p in problems if p.startswith("WARN:")]


def _form_fields(
    email: str, antenna_type: str, height_m: float, mode: str, seqnum: str
) -> dict[str, str]:
    """Multipart fields mirroring the OPUS upload page defaults."""
    return {
        "email_address": email,
        "height": f"{height_m:.3f}",
        "ant_type": antenna_type,
        "opusOption": "1" if mode == "static" else "2",
        "seqnum": seqnum,
        "theHost1": "www.ngs.noaa.gov",
        "submit_database": "2",
        "extend_code": "0",
        "share": "2",
        "xml_code": "0",
        "set_profile": "0",
        "delete_profile": "0",
        "selectList1": "",
        "geoid_model": "",
        "SolutionFormat": "",
        "state_plane": "",
        "project_name": "",
        "MyProfile": "",
        "sharedOption": "2",
    }


def _post_via_session(url, filename, payload, data, timeout, session):
    resp = session.post(
        url, files={"uploadfile": (filename, payload)}, data=data, timeout=timeout
    )
    body = resp.text
    if isinstance(body, (bytes, bytearray)):
        body = bytes(body).decode("utf-8", errors="replace")
    return int(resp.status_code), str(body)


def _post_via_requests(url, filename, payload, data, timeout):
    resp = _requests.post(
        url,
        files={
            "uploadfile": (
                filename,
                io.BytesIO(payload),
                "application/octet-stream",
            )
        },
        data=data,
        timeout=timeout,
    )
    return int(resp.status_code), resp.text


def _post_via_urllib(url, filename, payload, data, timeout):
    """Hand-built multipart/form-data POST (stdlib fallback)."""
    boundary = "----survey-opus-" + uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in data.items():
        parts.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8")
        )
    parts.append(
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="uploadfile"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
        + payload
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "User-Agent": "survey-opus/0.1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:  # e.g. 4xx/5xx: still a response
        return int(exc.code), exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise OpusError(f"OPUS upload POST failed: {exc}") from exc


def submit(
    rinex_path,
    email,
    antenna_type,
    antenna_height,
    mode="static",
    timeout=60,
    session=None,
) -> SubmissionReceipt:
    """Submit a RINEX observation file to NGS OPUS. Exactly one POST attempt.

    Validation order: mode, email, file existence, NGS filename rule,
    RINEX header parse + OPUS validation (hard problems raise
    :class:`OpusError`; ``WARN:`` advisories are echoed on the receipt).

    Args:
        rinex_path: path to the RINEX observation file.
        email: solution-report recipient (validated, lowercased).
        antenna_type: NGS antenna code, e.g. ``"TRM57971.00"``.
        antenna_height: meters above the mark (sent with 3 decimals).
        mode: ``"static"`` or ``"rapid-static"``.
        timeout: seconds for the single POST attempt.
        session: optional requests-like object with
            ``.post(url, files=..., data=..., timeout=...)`` (enables tests).

    Returns:
        SubmissionReceipt with the HTTP status and first ~500 chars of body.
    """
    if mode not in ("static", "rapid-static"):
        raise OpusError(f"mode must be 'static' or 'rapid-static', got {mode!r}")

    address = _validate_email(email)

    path = Path(rinex_path)
    if not path.is_file():
        raise OpusError(f"RINEX file not found: {rinex_path}")
    _validate_filename(path.name)

    try:
        height_m = float(antenna_height)
    except (TypeError, ValueError):
        raise OpusError(
            f"antenna height must be numeric (meters), got {antenna_height!r}"
        ) from None

    warnings = _validate_rinex(path)

    seqnum = datetime.datetime.now(datetime.timezone.utc).strftime("OP%Y%m%d%H%M%S")
    url = OPUS_UPLOAD_URL if mode == "static" else OPUS_RS_UPLOAD_URL
    data = _form_fields(address, antenna_type, height_m, mode, seqnum)
    payload = path.read_bytes()

    if session is not None:
        status, body = _post_via_session(url, path.name, payload, data, timeout, session)
    elif _requests is not None:
        status, body = _post_via_requests(url, path.name, payload, data, timeout)
    else:  # pragma: no cover - requests is installed in practice
        status, body = _post_via_urllib(url, path.name, payload, data, timeout)

    return SubmissionReceipt(
        submitted_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        email=address,
        rinex_filename=path.name,
        antenna_type=antenna_type,
        antenna_height=height_m,
        mode=mode,
        endpoint_url=url,
        seqnum=seqnum,
        response_status=status,
        response_excerpt=body[:500],
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# parse_solution()
# ---------------------------------------------------------------------------

_REPORT_MARKER = "NGS OPUS SOLUTION REPORT"


@dataclasses.dataclass
class Coordinate:
    """One reference-frame realization of the solved position."""

    frame: str  # "NAD83(2011)" / "ITRF2014" (or "IGS08"/"IGS14" as reported)
    epoch: str  # e.g. "2010.0000"
    lat_deg: float  # decimal degrees
    lon_deg: float  # decimal degrees, signed (-180..180)
    ell_ht_m: float


@dataclasses.dataclass
class GridCoordinate:
    """Projected coordinates from the UTM / SPC section."""

    system: str  # "UTM" / "SPC"
    zone: str  # "18N" / "3101 NY W" as reported
    northing_m: float
    easting_m: float


@dataclasses.dataclass
class OpusSolution:
    file: str  # FILE: echo line
    email: str  # USER: echo line
    processing_date: str  # DATE: echo line
    nad83: Coordinate | None
    itrf: Coordinate | None
    utm: GridCoordinate | None
    spc: GridCoordinate | None
    overall_rms_m: float | None
    pct_obs_used: float | None
    pct_ambiguities_fixed: float | None
    peak_to_peak_m: dict[str, float]  # {"lat":..,"lon":..,"ht":..} (NAD83 column)
    base_stations: list[str]  # CORS PIDs, in report order
    software: str  # SOFTWARE: provenance (sans START: tail)
    ephemeris: str  # EPHEMERIS: provenance (sans STOP: tail)
    raw_text: str


def _line_value(text: str, label: str) -> str | None:
    """Value after a line-leading ``LABEL:`` (e.g. ``FILE:``, ``USER:``)."""
    m = re.search(
        r"(?m)^[ \t]*" + re.escape(label) + r"[ \t]*([^\n]*?)[ \t]*$", text
    )
    return m.group(1).strip() if m else None


def _dms_to_deg(deg: str, minutes: str, seconds: str) -> float:
    return float(deg) + float(minutes) / 60.0 + float(seconds) / 3600.0


def _float_search(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None


# LAT:  dd mm ss.sssss  pp(m)   dd mm ss.sssss  pp(m)   (NAD83, then ITRF)
_LAT_RE = re.compile(
    r"(?m)^[ \t]*LAT:[ \t]*(\d+)[ \t]+(\d+)[ \t]+([\d.]+)"
    r"[ \t]+([\d.]+)\(m\)"
    r"[ \t]+(\d+)[ \t]+(\d+)[ \t]+([\d.]+)"
    r"[ \t]+([\d.]+)\(m\)"
)
_WLON_RE = re.compile(
    r"(?m)^[ \t]*W[ \t]*LON:[ \t]*(\d+)[ \t]+(\d+)[ \t]+([\d.]+)"
    r"[ \t]+([\d.]+)\(m\)"
    r"[ \t]+(\d+)[ \t]+(\d+)[ \t]+([\d.]+)"
    r"[ \t]+([\d.]+)\(m\)"
)
_ELON_RE = re.compile(
    r"(?m)^[ \t]*E[ \t]*LON:[ \t]*(\d+)[ \t]+(\d+)[ \t]+([\d.]+)"
    r"[ \t]+([\d.]+)\(m\)"
    r"[ \t]+(\d+)[ \t]+(\d+)[ \t]+([\d.]+)"
    r"[ \t]+([\d.]+)\(m\)"
)
_ELHGT_RE = re.compile(
    r"(?m)^[ \t]*EL[ \t]*HGT:[ \t]*([+-]?[\d.]+)\(m\)"
    r"[ \t]+([\d.]+)\(m\)"
    r"[ \t]+([+-]?[\d.]+)\(m\)"
    r"[ \t]+([\d.]+)\(m\)"
)
_REF_FRAME_RE = re.compile(
    r"REF[ \t]+FRAME:[ \t]*(\S+?)[ \t]*\(EPOCH:([0-9.]+)\)"
    r"[ \t]+(\S+?)[ \t]*\(EPOCH:([0-9.]+)\)"
)
_PID_RE = re.compile(r"[A-Z]{2}\d{4}")


def _parse_frames(text: str):
    """Return (nad83 Coordinate|None, itrf Coordinate|None, peak_to_peak dict)."""
    ref = _REF_FRAME_RE.search(text)
    if ref:
        # Report prints NAD_83(2011); contract uses NAD83(2011).
        frame1 = ref.group(1).replace("NAD_83", "NAD83")
        epoch1, frame2, epoch2 = ref.group(2), ref.group(3), ref.group(4)
    else:
        frame1 = epoch1 = frame2 = epoch2 = None

    lat_m = _LAT_RE.search(text)
    wlon_m = _WLON_RE.search(text)
    elon_m = _ELON_RE.search(text)
    hgt_m = _ELHGT_RE.search(text)

    peak_to_peak: dict[str, float] = {}

    def lon_decimal(which: int) -> float | None:
        # which: 0 = NAD83 column, 1 = ITRF column
        if wlon_m:
            d, mi, s = wlon_m.group(1 + 4 * which), wlon_m.group(2 + 4 * which), wlon_m.group(3 + 4 * which)
            return -_dms_to_deg(d, mi, s)
        if elon_m:  # fallback: 0..360 E longitude -> signed
            d, mi, s = elon_m.group(1 + 4 * which), elon_m.group(2 + 4 * which), elon_m.group(3 + 4 * which)
            e = _dms_to_deg(d, mi, s)
            return e - 360.0 if e > 180.0 else e
        return None

    nad83 = itrf = None
    if lat_m and hgt_m and (wlon_m or elon_m):
        lat0 = _dms_to_deg(lat_m.group(1), lat_m.group(2), lat_m.group(3))
        lat1 = _dms_to_deg(lat_m.group(5), lat_m.group(6), lat_m.group(7))
        lon0, lon1 = lon_decimal(0), lon_decimal(1)
        ht0, ht1 = float(hgt_m.group(1)), float(hgt_m.group(3))
        if lon0 is not None and frame1 and epoch1:
            nad83 = Coordinate(
                frame=frame1, epoch=epoch1,
                lat_deg=lat0, lon_deg=lon0, ell_ht_m=ht0,
            )
            peak_to_peak["lat"] = float(lat_m.group(4))
            peak_to_peak["lon"] = float(
                wlon_m.group(4) if wlon_m else elon_m.group(4)
            )
            peak_to_peak["ht"] = float(hgt_m.group(2))
        if lon1 is not None and frame2 and epoch2:
            itrf = Coordinate(
                frame=frame2, epoch=epoch2,
                lat_deg=lat1, lon_deg=lon1, ell_ht_m=ht1,
            )
    return nad83, itrf, peak_to_peak


def _parse_grids(text: str, nad83: Coordinate | None):
    """Return (utm GridCoordinate|None, spc GridCoordinate|None)."""
    utm = spc = None
    utm_m = re.search(r"UTM[ \t]*\(Zone[ \t]*(\d+)\)", text)
    north_m = re.search(
        r"(?m)^[ \t]*Northing[ \t]*\(Y\)[ \t]*\[meters\][ \t]*"
        r"([+-]?[\d.]+)(?:[ \t]+([+-]?[\d.]+))?",
        text,
    )
    east_m = re.search(
        r"(?m)^[ \t]*Easting[ \t]*\(X\)[ \t]*\[meters\][ \t]*"
        r"([+-]?[\d.]+)(?:[ \t]+([+-]?[\d.]+))?",
        text,
    )
    if utm_m and north_m and east_m:
        zone = utm_m.group(1)
        if nad83 is not None:
            zone += "N" if nad83.lat_deg >= 0 else "S"
        utm = GridCoordinate(
            system="UTM",
            zone=zone,
            northing_m=float(north_m.group(1)),
            easting_m=float(east_m.group(1)),
        )
    spc_m = re.search(r"SPC[ \t]*\(([^)]*)\)", text)
    if (
        spc_m
        and north_m
        and north_m.group(2)
        and east_m
        and east_m.group(2)
    ):
        spc = GridCoordinate(
            system="SPC",
            zone=spc_m.group(1).strip(),
            northing_m=float(north_m.group(2)),
            easting_m=float(east_m.group(2)),
        )
    return utm, spc


def _parse_base_stations(text: str) -> list[str]:
    """CORS PIDs from BASE STATIONS USED, in report order.

    Rows start with the PID; wrapped continuation lines do not, so they are
    naturally skipped. Stops before NEAREST NGS PUBLISHED CONTROL POINT.
    """
    m = re.search(r"BASE[ \t]+STATIONS[ \t]+USED", text)
    if not m:
        return []
    tail = text[m.end():]
    stop = re.search(
        r"(?m)^[ \t]*NEAREST[ \t]+NGS[ \t]+PUBLISHED[ \t]+CONTROL[ \t]+POINT",
        tail,
    )
    if stop:
        tail = tail[: stop.start()]
    stations: list[str] = []
    for line in tail.splitlines():
        s = line.strip()
        if not s or re.match(r"(?i)^PID\b", s):
            continue  # blank line or the column-header row
        token = s.split()[0]
        if _PID_RE.fullmatch(token) and token not in stations:
            stations.append(token)
    return stations


def parse_solution(report_text: str) -> OpusSolution:
    """Parse a plain-text NGS OPUS solution report (the emailed body).

    Tolerant of standard vs extended variants: any missing section yields
    ``None`` (or ``[]``/``{}``/``""``) rather than a fabricated value.

    Raises:
        OpusError: if the text lacks the ``NGS OPUS SOLUTION REPORT`` marker.
    """
    if not report_text or _REPORT_MARKER not in report_text:
        raise OpusError(
            "not an NGS OPUS solution report: "
            "'NGS OPUS SOLUTION REPORT' marker not found"
        )
    text = report_text

    file_val = _line_value(text, "FILE:") or ""

    email = ""
    processing_date = ""
    user_val = _line_value(text, "USER:")
    if user_val:
        dm = re.search(r"DATE:[ \t]*([^\n]+)$", user_val)
        if dm:
            processing_date = dm.group(1).strip()
            email = user_val[: dm.start()].strip()
        else:
            email = user_val.strip()
    if not processing_date:
        processing_date = _line_value(text, "DATE:") or ""

    nad83, itrf, peak_to_peak = _parse_frames(text)
    utm, spc = _parse_grids(text, nad83)

    sw_line = _line_value(text, "SOFTWARE:")
    software = re.split(r"[ \t]+START:", sw_line)[0].strip() if sw_line else ""
    eph_line = _line_value(text, "EPHEMERIS:")
    ephemeris = re.split(r"[ \t]+STOP:", eph_line)[0].strip() if eph_line else ""

    return OpusSolution(
        file=file_val,
        email=email,
        processing_date=processing_date,
        nad83=nad83,
        itrf=itrf,
        utm=utm,
        spc=spc,
        overall_rms_m=_float_search(r"OVERALL[ \t]*RMS:[ \t]*([\d.]+)\(m\)", text),
        pct_obs_used=_float_search(
            r"OBS[ \t]*USED:[ \t]*\d+[ \t]*/[ \t]*\d+[ \t]*:[ \t]*([\d.]+)%", text
        ),
        pct_ambiguities_fixed=_float_search(
            r"#?[ \t]*FIXED[ \t]*AMB:[ \t]*\d+[ \t]*/[ \t]*\d+[ \t]*:[ \t]*([\d.]+)%",
            text,
        ),
        peak_to_peak_m=peak_to_peak,
        base_stations=_parse_base_stations(text),
        software=software,
        ephemeris=ephemeris,
        raw_text=report_text,
    )


def solution_to_json(solution: OpusSolution) -> str:
    """Serialize an OpusSolution to JSON (``default=str`` for safety)."""
    return json.dumps(dataclasses.asdict(solution), indent=2, default=str)
