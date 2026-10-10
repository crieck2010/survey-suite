"""survey-gnss: GNSS engine for surveying.

Pure-Python, dependency-free: NMEA 0183 parsing (GGA/RMC/GSA/GSV/VTG with
checksum validation), WGS84 geodetic/ECEF conversion, baseline vectors,
dilution of precision from satellite geometry, and O(1)-memory static
session statistics. No UI, no file I/O -- log files stream through a
generator, and positions come out as decimal degrees / ECEF ready for
survey-geodesy and survey-cogo.
"""

__version__ = "0.1.0"

from .coords import (
    baseline,
    ecef_to_geodetic,
    geodetic_to_ecef,
    unit_vectors_to_enu,
)
from .dop import Dop, dop_from_unit_vectors, dop_quality
from .nmea import (
    GgaFix,
    GsaFix,
    GsvSentence,
    RmcFix,
    Satellite,
    VtgFix,
    checksum_ok,
    iter_sentences,
    nmea_date_to_tuple,
    nmea_time_to_tuple,
    nmea_to_decimal,
    parse_gsa,
    parse_gsv,
    parse_gga,
    parse_rmc,
    parse_sentence,
    parse_vtg,
    sentence_type,
)
from .session import Fix, Session, assess_quality

__all__ = [
    "__version__",
    "GgaFix", "RmcFix", "GsaFix", "GsvSentence", "Satellite", "VtgFix",
    "checksum_ok", "sentence_type",
    "nmea_to_decimal", "nmea_time_to_tuple", "nmea_date_to_tuple",
    "parse_gga", "parse_rmc", "parse_gsa", "parse_gsv", "parse_vtg",
    "parse_sentence", "iter_sentences",
    "geodetic_to_ecef", "ecef_to_geodetic", "baseline",
    "unit_vectors_to_enu",
    "Dop", "dop_from_unit_vectors", "dop_quality",
    "Fix", "Session", "assess_quality",
]
