"""NMEA 0183 sentence parsing.

Interoperability: NMEA 0183 is the lingua franca of GNSS receivers --
every receiver, from survey-grade to a phone, emits these sentences.
Parsing them here means logged data from any hardware flows into the
engine with no vendor-specific adapter. Talker IDs (GP, GL, GA, GB, GQ,
GI, GN, ...) are accepted generically; only the sentence type matters.

Scaling: :func:`iter_sentences` is a generator -- multi-gigabyte log
files stream through O(1) memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional


# ---------------------------------------------------------------------------
# checksums and field helpers
# ---------------------------------------------------------------------------

def checksum_ok(sentence: str) -> bool:
    """Validate the ``*HH`` checksum of a raw NMEA sentence."""
    sentence = sentence.strip()
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, _, check = sentence[1:].partition("*")
    try:
        expected = int(check[:2], 16)
    except ValueError:
        return False
    actual = 0
    for ch in body:
        actual ^= ord(ch)
    return actual == expected


def _fields(sentence: str) -> list[str]:
    body = sentence.strip()[1:].split("*")[0]
    return body.split(",")


def sentence_type(sentence: str) -> str:
    """Last three characters of the talker+type tag, e.g. ``'GGA'``."""
    tag = _fields(sentence)[0]
    return tag[-3:]


def nmea_to_decimal(coord: str, hemisphere: str) -> Optional[float]:
    """``ddmm.mmmm`` + hemisphere -> signed decimal degrees (None if empty)."""
    coord = coord.strip()
    hemisphere = hemisphere.strip().upper()
    if not coord or hemisphere not in ("N", "S", "E", "W"):
        return None
    # Latitude has 2 degree digits, longitude 3; split on the decimal point.
    dot = coord.find(".")
    deg_len = dot - 2
    if deg_len < 1:
        return None
    degrees = float(coord[:deg_len])
    minutes = float(coord[deg_len:])
    value = degrees + minutes / 60.0
    if hemisphere in ("S", "W"):
        value = -value
    return value


def nmea_time_to_tuple(t: str) -> Optional[tuple[int, int, float]]:
    """``hhmmss.ss`` -> (hour, minute, second)."""
    t = t.strip()
    if len(t) < 6:
        return None
    try:
        return (int(t[0:2]), int(t[2:4]), float(t[4:]))
    except ValueError:
        return None


def nmea_date_to_tuple(d: str) -> Optional[tuple[int, int, int]]:
    """``ddmmyy`` -> (year, month, day); 80-99 map to 19xx, else 20xx."""
    d = d.strip()
    if len(d) != 6:
        return None
    try:
        day, mon, yy = int(d[0:2]), int(d[2:4]), int(d[4:6])
    except ValueError:
        return None
    year = 1900 + yy if yy >= 80 else 2000 + yy
    return (year, mon, day)


def _opt_float(s: str) -> Optional[float]:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _opt_int(s: str) -> Optional[int]:
    s = s.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# sentence dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GgaFix:
    """Global Positioning System Fix Data."""
    time: Optional[tuple[int, int, float]]
    lat: Optional[float]
    lon: Optional[float]
    quality: int            # 0=invalid 1=GPS 2=DGPS 4=RTK fixed 5=RTK float
    num_sats: Optional[int]
    hdop: Optional[float]
    altitude: Optional[float]      # metres above mean sea level
    geoid_sep: Optional[float]     # metres


@dataclass(frozen=True)
class RmcFix:
    """Recommended Minimum Specific GNSS Data."""
    time: Optional[tuple[int, int, float]]
    date: Optional[tuple[int, int, int]]
    status: str                    # 'A' = active/valid, 'V' = void
    lat: Optional[float]
    lon: Optional[float]
    speed_knots: Optional[float]
    course_deg: Optional[float]


@dataclass(frozen=True)
class GsaFix:
    """GNSS DOP and Active Satellites."""
    mode: str                      # 'A' = auto, 'M' = manual
    fix_type: int                  # 1=none 2=2D 3=3D
    sats_used: tuple[int, ...]
    pdop: Optional[float]
    hdop: Optional[float]
    vdop: Optional[float]


@dataclass(frozen=True)
class Satellite:
    """One satellite entry from a GSV sentence."""
    prn: int
    elevation_deg: Optional[float]
    azimuth_deg: Optional[float]
    snr_dbhz: Optional[float]


@dataclass(frozen=True)
class GsvSentence:
    """GNSS Satellites in View (one of a multi-sentence group)."""
    total_messages: int
    message_number: int
    total_sats: int
    satellites: tuple[Satellite, ...]


@dataclass(frozen=True)
class VtgFix:
    """Course Over Ground and Ground Speed."""
    course_true: Optional[float]
    course_mag: Optional[float]
    speed_knots: Optional[float]
    speed_kmh: Optional[float]


# ---------------------------------------------------------------------------
# parsers
# ---------------------------------------------------------------------------

def parse_gga(sentence: str) -> GgaFix:
    f = _fields(sentence)
    f += [""] * (15 - len(f))
    return GgaFix(
        time=nmea_time_to_tuple(f[1]),
        lat=nmea_to_decimal(f[2], f[3]),
        lon=nmea_to_decimal(f[4], f[5]),
        quality=_opt_int(f[6]) or 0,
        num_sats=_opt_int(f[7]),
        hdop=_opt_float(f[8]),
        altitude=_opt_float(f[9]),
        geoid_sep=_opt_float(f[11]),
    )


def parse_rmc(sentence: str) -> RmcFix:
    f = _fields(sentence)
    f += [""] * (12 - len(f))
    return RmcFix(
        time=nmea_time_to_tuple(f[1]),
        date=nmea_date_to_tuple(f[9]),
        status=f[2].strip().upper(),
        lat=nmea_to_decimal(f[3], f[4]),
        lon=nmea_to_decimal(f[5], f[6]),
        speed_knots=_opt_float(f[7]),
        course_deg=_opt_float(f[8]),
    )


def parse_gsa(sentence: str) -> GsaFix:
    f = _fields(sentence)
    f += [""] * (18 - len(f))
    sats = tuple(s for s in (_opt_int(x) for x in f[3:15]) if s is not None)
    return GsaFix(
        mode=f[1].strip().upper(),
        fix_type=_opt_int(f[2]) or 1,
        sats_used=sats,
        pdop=_opt_float(f[15]),
        hdop=_opt_float(f[16]),
        vdop=_opt_float(f[17]),
    )


def parse_gsv(sentence: str) -> GsvSentence:
    f = _fields(sentence)
    sats: list[Satellite] = []
    for i in range(4, len(f) - 3, 4):
        prn = _opt_int(f[i])
        if prn is None:
            continue
        sats.append(Satellite(
            prn=prn,
            elevation_deg=_opt_float(f[i + 1]),
            azimuth_deg=_opt_float(f[i + 2]),
            snr_dbhz=_opt_float(f[i + 3]),
        ))
    return GsvSentence(
        total_messages=_opt_int(f[1]) or 0,
        message_number=_opt_int(f[2]) or 0,
        total_sats=_opt_int(f[3]) or 0,
        satellites=tuple(sats),
    )


def parse_vtg(sentence: str) -> VtgFix:
    f = _fields(sentence)
    f += [""] * (10 - len(f))
    return VtgFix(
        course_true=_opt_float(f[1]),
        course_mag=_opt_float(f[3]),
        speed_knots=_opt_float(f[5]),
        speed_kmh=_opt_float(f[7]),
    )


_PARSERS = {
    "GGA": parse_gga,
    "RMC": parse_rmc,
    "GSA": parse_gsa,
    "GSV": parse_gsv,
    "VTG": parse_vtg,
}


def parse_sentence(sentence: str, check_checksum: bool = True):
    """Parse any supported NMEA sentence; None for unknown/unsupported types.

    Raises ValueError on checksum failure when ``check_checksum`` is true.
    """
    sentence = sentence.strip()
    if check_checksum and not checksum_ok(sentence):
        raise ValueError(f"Bad checksum: {sentence[:20]}...")
    parser = _PARSERS.get(sentence_type(sentence))
    if parser is None:
        return None
    return parser(sentence)


def iter_sentences(lines: Iterable[str],
                   skip_bad: bool = True) -> Iterator:
    """Stream parsed sentences from lines (e.g. an open log file).

    With ``skip_bad=True`` (default) lines with bad checksums or unknown
    types are silently skipped; otherwise checksum failures raise.
    """
    for line in lines:
        line = line.strip()
        if not line.startswith("$"):
            continue
        try:
            parsed = parse_sentence(line, check_checksum=True)
        except ValueError:
            if skip_bad:
                continue
            raise
        if parsed is not None:
            yield parsed
