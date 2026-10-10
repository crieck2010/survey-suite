"""survey-opus — NGS OPUS (Online Positioning User Service) client.

Validate RINEX observation files, submit them to NOAA's National Geodetic
Survey OPUS service, and parse the emailed solution reports.

Public API (all re-exports):
    RINEX side:  parse_header, validate_for_opus, RinexHeader, RinexError
    OPUS side:   submit, parse_solution, solution_to_json,
                 SubmissionReceipt, OpusSolution, Coordinate, GridCoordinate,
                 OpusError, OPUS_UPLOAD_URL, OPUS_RS_UPLOAD_URL
"""

__version__ = "0.1.0"

from survey_opus.client import (
    OPUS_RS_UPLOAD_URL,
    OPUS_UPLOAD_URL,
    Coordinate,
    GridCoordinate,
    OpusError,
    OpusSolution,
    SubmissionReceipt,
    parse_solution,
    solution_to_json,
    submit,
)
from survey_opus.rinex import (
    RinexError,
    RinexHeader,
    parse_header,
    validate_for_opus,
)

__all__ = [
    "__version__",
    # endpoints
    "OPUS_UPLOAD_URL",
    "OPUS_RS_UPLOAD_URL",
    # rinex
    "parse_header",
    "validate_for_opus",
    "RinexHeader",
    "RinexError",
    # client
    "submit",
    "SubmissionReceipt",
    "OpusError",
    "parse_solution",
    "solution_to_json",
    "OpusSolution",
    "Coordinate",
    "GridCoordinate",
]
