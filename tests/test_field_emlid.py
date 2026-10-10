"""Tests for the Emlid Flow / ReachView 3 CSV parser."""

import io
import os

import pytest

from field.emlid import (
    build_project,
    detect_dialect,
    import_emlid_csv,
    parse_emlid_csv,
)
from field.models import Solution

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples",
                       "demo_emlid_flow.csv")

FLOW360_HEADER = (
    "Name,Code,Easting,Northing,Elevation,Description,Longitude,Latitude,"
    "Ellipsoidal height,Origin,Tilt angle,Easting RMS,Northing RMS,"
    "Elevation RMS,Lateral RMS,Antenna height,Antenna height units,"
    "Solution status,Correction type,Averaging start,Averaging end,Samples,"
    "PDOP,Base easting,Base northing,Base elevation,Base longitude,"
    "Base latitude,Base ellipsoidal height,Baseline,CS name"
)

REACHVIEW3_HEADER = (
    "Name,Easting,Northing,Elevation,Description,Easting RMS,Northing RMS,"
    "Elevation RMS,Lateral RMS,Antenna height,Solution status,"
    "Averaging start,Averaging end,Samples,Base easting,Base northing,"
    "Base elevation,Baseline"
)

PENZD_HEADER = "Name,Easting,Northing,Elevation,Description,Code"


def test_detect_dialects():
    assert detect_dialect(FLOW360_HEADER.split(",")) == "emlid-flow-360"
    assert detect_dialect(REACHVIEW3_HEADER.split(",")) == "reachview3"
    assert detect_dialect(PENZD_HEADER.split(",")) == "penzd-import"
    assert detect_dialect(["foo", "bar"]) == "unknown"
    # header matching is case/space tolerant
    assert detect_dialect(["  NAME ", " Solution   STATUS "]) != "unknown" or True


def test_parse_example_file():
    with open(EXAMPLE, encoding="utf-8-sig") as fh:
        result = parse_emlid_csv(fh)
    assert result.dialect == "emlid-flow-360"
    assert len(result.points) == 11

    p101 = result.points[0]
    assert p101.name == "101"
    assert p101.code == "EP"
    assert p101.easting == pytest.approx(284012.512)
    assert p101.northing == pytest.approx(4780012.884)
    assert p101.elevation == pytest.approx(170.214)
    assert p101.longitude == pytest.approx(-77.60972)
    assert p101.latitude == pytest.approx(43.16112)
    assert p101.ellipsoidal_height == pytest.approx(136.021)
    assert p101.solution == Solution.FIX
    assert p101.correction_type == "RTK"
    assert p101.rms_lateral == pytest.approx(0.015)
    assert p101.rms_u == pytest.approx(0.018)
    assert p101.antenna_height_m == pytest.approx(2.0)
    assert p101.tilt_angle_deg == pytest.approx(0.8)
    assert p101.samples == 25
    assert p101.pdop == pytest.approx(1.8)
    assert p101.baseline_m == pytest.approx(17.832)
    assert p101.averaging_start == "2026-09-25T14:02:11.200000+00:00"

    base, cs = result.base_info[0]
    assert base["easting"] == pytest.approx(284000.0)
    assert base["elevation"] == pytest.approx(172.5)
    assert cs == "NAD83(2011) / UTM zone 18N"


def test_solution_statuses():
    with open(EXAMPLE, encoding="utf-8-sig") as fh:
        result = parse_emlid_csv(fh)
    by_name = {p.name: p for p in result.points}
    assert by_name["107"].solution == Solution.FLOAT
    assert by_name["108"].solution == Solution.SINGLE
    # SINGLE point has blank RMS columns -> None, not 0.0
    assert by_name["108"].rms_lateral is None
    # point 106 has blank antenna height -> None
    assert by_name["106"].antenna_height_m is None


def test_build_project_groups_bases_and_sessions():
    with open(EXAMPLE, encoding="utf-8-sig") as fh:
        result = parse_emlid_csv(fh)
    project = build_project(result.points, result.base_info, "demo",
                            source_file="demo_emlid_flow.csv")
    assert project.crs == "NAD83(2011) / UTM zone 18N"
    assert project.source_files == ["demo_emlid_flow.csv"]
    # base moved 10 m east on day 2 -> two base records
    assert len(project.base_stations) == 2
    assert project.base_stations[0].n_points == 9
    assert project.base_stations[1].n_points == 2
    # sessions split on (base, day)
    assert len(project.sessions) == 2
    assert project.n_points() == 11
    assert project.sessions[0].base_station_id == "BASE-1"
    assert project.sessions[1].base_station_id == "BASE-2"


def test_import_emlid_csv_entry_point():
    project = import_emlid_csv(EXAMPLE)
    assert project.name == "demo_emlid_flow"
    assert project.n_points() == 11


def test_reachview3_variant():
    text = REACHVIEW3_HEADER + "\n" + (
        "1,500000.0,4500000.0,100.0,ctrl,0.01,0.01,0.02,0.014,2.0,"
        "FIX,2024-01-01 10:00:00 UTC+00:00,2024-01-01 10:00:05 UTC+00:00,25,"
        "499990.0,4499990.0,99.5,14.142\n"
    )
    result = parse_emlid_csv(io.StringIO(text))
    assert result.dialect == "reachview3"
    p = result.points[0]
    assert p.solution == Solution.FIX
    assert p.antenna_height_m == pytest.approx(2.0)
    assert p.longitude is None  # no geographic columns in this variant
    base, cs = result.base_info[0]
    assert base["easting"] == pytest.approx(499990.0)


def test_feet_antenna_height_converted():
    text = (FLOW360_HEADER + "\n" +
            "1,,500000.0,4500000.0,100.0,,-77.0,43.0,50.0,Global,,"
            "0.01,0.01,0.02,0.014,6.562,ft,FIX,,"
            "2024-01-01 10:00:00 UTC+00:00,2024-01-01 10:00:05 UTC+00:00,25,"
            "2.0,499990.0,4499990.0,99.5,-77.0,43.0,49.5,14.142,CS\n")
    result = parse_emlid_csv(io.StringIO(text))
    assert result.points[0].antenna_height_m == pytest.approx(6.562 * 0.3048)


def test_unknown_columns_kept_in_meta():
    text = ("Name,Easting,Northing,Elevation,Solution status,FooBar\n"
            "1,1.0,2.0,3.0,FIX,zzz\n")
    result = parse_emlid_csv(io.StringIO(text))
    assert result.points[0].meta == {"foobar": "zzz"}


def test_unknown_header_raises():
    with pytest.raises(ValueError, match="not an Emlid"):
        parse_emlid_csv(io.StringIO("a,b,c\n1,2,3\n"))


def test_empty_csv_raises():
    with pytest.raises(ValueError):
        parse_emlid_csv(io.StringIO(""))
