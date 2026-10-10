"""Tests for `field import --target-crs` (survey-crs reprojection).

Conventions: tests that need the optional survey-crs engine call
``pytest.importorskip("crs")`` inside the test so the suite stays green when
it is not installed; the missing-backend path is tested explicitly.
"""

import json
import os
import sys
from datetime import datetime

import pytest

from field.adapters import to_adjust_control, to_adjust_observations
from field.cli import main
from field.emlid import import_emlid_csv
from field.jobfile import dump_job, load_job, read_job
from field.reproject import CrsReprojectError, reproject_project


def _need_crs():
    return pytest.importorskip(
        "crs", reason="survey-crs not installed (pip install survey-crs)")


# NGS DI0446 (CENTRAL ISLIP CORS ARP): NAD83(2011) ADJUSTED position, as
# cited in survey-crs tests/test_published.py ("DI0446 NY Long Island (ftUS)").
def _dms(d, m, s):
    return d + m / 60.0 + s / 3600.0


DI0446_LAT = _dms(40, 45, 38.23676)
DI0446_LON = -_dms(73, 11, 51.78749)
# Oracle from survey-crs's published-coordinate tests: project() of the above
# lat/lon into EPSG:6539 gives E 1206501.82 / N 217409.36 ftUS (+-0.02).
DI0446_E_FTUS = 1206501.82
DI0446_N_FTUS = 217409.36

GEO_HEADER = (
    "Name,Code,Easting,Northing,Elevation,Description,Longitude,Latitude,"
    "Ellipsoidal height,Origin,Easting RMS,Northing RMS,Elevation RMS,"
    "Lateral RMS,Antenna height,Antenna height units,Solution status,"
    "Averaging start,Averaging end,Samples,PDOP,"
    "Base longitude,Base latitude,Base ellipsoidal height,Baseline,CS name"
)

GEO_ROW = (
    "DI0446,CORS,,,,,{lon:.10f},{lat:.10f},28.554,Global,"
    "0.011,0.010,0.018,0.015,2.000,m,FIX,"
    "2026-09-25 14:02:11.2 UTC+00:00,2026-09-25 14:02:16.2 UTC+00:00,25,1.8,"
    "-73.19770,40.76060,30.112,,WGS 84"
).format(lon=DI0446_LON, lat=DI0446_LAT)

PROJ_HEADER = (
    "Name,Code,Easting,Northing,Elevation,Description,Solution status,"
    "Easting RMS,Northing RMS,Elevation RMS,Lateral RMS,"
    "Base easting,Base northing,Base elevation,CS name"
)


def _write(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(header + "\n")
        for row in rows:
            fh.write(row + "\n")
    return path


def _geo_csv(tmp_path, name="geo.csv"):
    return _write(str(tmp_path / name), GEO_HEADER, [GEO_ROW])


def _proj_csv(tmp_path, cs_name, name="proj.csv"):
    rows = [
        f"P1,EP,367742.490,66266.506,28.554,,FIX,0.011,0.010,0.018,0.015,"
        f"367700.000,66200.000,30.000,{cs_name}",
        f"P2,EP,367800.123,66300.456,28.601,,FIX,0.012,0.011,0.019,0.016,"
        f"367700.000,66200.000,30.000,{cs_name}",
    ]
    return _write(str(tmp_path / name), PROJ_HEADER, rows)


# ---------------------------------------------------------------------------
# (a) geographic -> projected, oracle-checked against survey-crs published values


@pytest.mark.parametrize("spec", ["EPSG:6539", "6539", "New York Long Island (ftUS)"])
def test_geo_to_ny_long_island_ftus(tmp_path, capsys, spec):
    _need_crs()
    csv_path = _geo_csv(tmp_path)
    out = str(tmp_path / "job.sfield.json")
    rc = main(["import", csv_path, "-o", out, "--name", "ny-li", "--target-crs", spec])
    assert rc == 0
    captured = capsys.readouterr()
    # The datum-shift warning must surface in the import report, not be buried.
    assert "crs warning:" in captured.out
    assert "~2 m" in captured.out or "2 m horizontal" in captured.out

    project = read_job(out)
    assert project.crs == "NAD83(2011) / New York Long Island (ftUS)"
    (point,) = list(project.iter_points())
    # Oracle: survey-crs tests/test_published.py, DI0446 -> EPSG:6539.
    # The WGS 84 -> NAD83(2011) leg is survey-crs's null approximation
    # (identity), so the published project() values hold to 0.02 ftUS.
    assert abs(point.easting - DI0446_E_FTUS) <= 0.02, point.easting
    assert abs(point.northing - DI0446_N_FTUS) <= 0.02, point.northing
    # Untouched metadata: geographic position, RMS, solution, antenna height.
    assert point.longitude == pytest.approx(DI0446_LON)
    assert point.latitude == pytest.approx(DI0446_LAT)
    assert point.rms_e == pytest.approx(0.011)
    assert point.rms_n == pytest.approx(0.010)
    assert point.rms_u == pytest.approx(0.018)
    assert point.rms_lateral == pytest.approx(0.015)
    assert point.solution == "FIX"
    assert point.antenna_height_m == pytest.approx(2.0)


def test_epsg_2263_clean_unknown_code_error(tmp_path, capsys):
    # EPSG:2263 (legacy NAD83(1986) NY Long Island) is NOT in the survey-crs
    # registry (NAD83(2011)-only SPCS); the failure must be clean + helpful.
    _need_crs()
    csv_path = _geo_csv(tmp_path)
    out = str(tmp_path / "job.sfield.json")
    rc = main(["import", csv_path, "-o", out, "--target-crs", "EPSG:2263"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "not in the survey-crs registry" in captured.err
    assert "6539" in captured.err  # points at the NAD83(2011) equivalent
    assert not os.path.exists(out)  # refused: nothing written


# ---------------------------------------------------------------------------
# (d) provenance block shape


def test_provenance_block_complete(tmp_path):
    _need_crs()
    csv_path = _geo_csv(tmp_path)
    out = str(tmp_path / "job.sfield.json")
    assert main(["import", csv_path, "-o", out, "--target-crs", "EPSG:6539"]) == 0
    with open(out, encoding="utf-8") as fh:
        env = json.load(fh)
    assert env["schema_version"] == 1  # additive: no schema bump
    prov = env["project"]["crs_provenance"]
    assert prov["source_crs"]["epsg"] == 4326
    assert prov["source_crs"]["datum"] == "WGS 84 (G2296)"
    assert prov["source_crs"]["as_recorded_in_csv"] == "WGS 84"
    assert prov["target_crs"]["epsg"] == 6539
    assert prov["target_crs"]["name"] == "NAD83(2011) / New York Long Island (ftUS)"
    assert prov["target_crs"]["datum"] == "NAD83(2011)"
    assert prov["target_crs"]["unit"] == "ftUS"
    tr = prov["transform"]
    assert tr["applied"] is True
    assert tr["n_points"] == 1
    assert tr["survey_crs_version"] == "0.1.0"
    assert tr["backend"] in ("internal", "survey-geodesy")
    dp = tr["datum_path"]
    assert dp["from_datum"] == "WGS 84 (G2296)"
    assert dp["to_datum"] == "NAD83(2011)"
    assert dp["method"] == "null-approximation"
    assert dp["accuracy_horizontal_m"] == pytest.approx(2.0)
    assert dp["region"] == "CONUS"
    assert dp["warning"]  # the "~2 m, not for survey control" warning
    assert any("2 m" in w for w in tr["warnings"])
    datetime.fromisoformat(tr["timestamp"])  # parses as ISO-8601
    assert prov["notes"]


def test_inspect_shows_provenance(tmp_path, capsys):
    _need_crs()
    csv_path = _geo_csv(tmp_path)
    out = str(tmp_path / "job.sfield.json")
    assert main(["import", csv_path, "-o", out, "--target-crs", "6539"]) == 0
    capsys.readouterr()
    assert main(["inspect", out]) == 0
    shown = capsys.readouterr().out
    assert "crs provenance:" in shown
    assert "EPSG:6539" in shown
    assert "null-approximation" in shown
    assert "2.0 m horizontal" in shown


# ---------------------------------------------------------------------------
# (b) no-flag path: byte-equivalent to v0.1.0


def test_no_flag_byte_equivalent_to_v010(tmp_path, capsys):
    csv_path = _proj_csv(tmp_path, "NAD83(2011) / New York Long Island (ftUS)")
    out = str(tmp_path / "job.sfield.json")
    rc = main(["import", csv_path, "-o", out, "--name", "bytecheck"])
    assert rc == 0
    with open(out, "rb") as fh:
        raw = fh.read()
    assert b"crs_provenance" not in raw
    # Exactly what the v0.1.0 code path (import -> validate -> write_job)
    # produces: no new keys, no reformatting.
    project = import_emlid_csv(csv_path, project_name="bytecheck")
    expected = (json.dumps(dump_job(project), indent=2, ensure_ascii=False) + "\n"
                ).encode("utf-8")
    assert raw.replace(b"\r\n", b"\n") == expected.replace(b"\r\n", b"\n")
    shown = capsys.readouterr().out
    assert "crs note:" not in shown and "crs warning:" not in shown


def test_no_flag_geo_csv_unchanged(tmp_path):
    # Geographic CSV without --target-crs: lat/lon only, as in v0.1.0.
    csv_path = _geo_csv(tmp_path)
    out = str(tmp_path / "job.sfield.json")
    assert main(["import", csv_path, "-o", out]) == 0
    project = read_job(out)
    assert project.crs == "WGS 84"
    assert project.crs_provenance is None
    (point,) = list(project.iter_points())
    assert not point.has_projected()
    assert point.has_geographic()


# ---------------------------------------------------------------------------
# (c) projected + mismatched explicit target -> loud refusal


def test_projected_mismatched_target_refused(tmp_path, capsys):
    _need_crs()
    # Source resolves (EPSG:6538) and differs from the target (EPSG:6539).
    csv_path = _proj_csv(tmp_path, "NAD83(2011) / New York Long Island")
    out = str(tmp_path / "job.sfield.json")
    rc = main(["import", csv_path, "-o", out, "--target-crs", "EPSG:6539"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "refusing" in captured.err
    assert "6538" in captured.err and "6539" in captured.err
    assert not os.path.exists(out)


def test_projected_unresolvable_source_refused(tmp_path, capsys):
    _need_crs()
    # "NAD83(2011) / UTM zone 18N" is not a survey-crs registry entry, so the
    # target cannot be verified against it: still a loud refusal, never a mix.
    csv_path = _proj_csv(tmp_path, "NAD83(2011) / UTM zone 18N")
    out = str(tmp_path / "job.sfield.json")
    rc = main(["import", csv_path, "-o", out, "--target-crs", "EPSG:6539"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "cannot map" in captured.err
    assert not os.path.exists(out)


def test_projected_matching_target_noop(tmp_path, capsys):
    _need_crs()
    csv_path = _proj_csv(tmp_path, "NAD83(2011) / New York Long Island (ftUS)")
    out = str(tmp_path / "job.sfield.json")
    rc = main(["import", csv_path, "-o", out, "--target-crs", "6539"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "already in" in captured.out and "no transform applied" in captured.out
    project = read_job(out)
    pts = list(project.iter_points())
    assert pts[0].easting == pytest.approx(367742.490)  # untouched
    assert pts[0].northing == pytest.approx(66266.506)
    prov = project.crs_provenance
    assert prov["transform"]["applied"] is False
    assert prov["source_crs"]["epsg"] == prov["target_crs"]["epsg"] == 6539


# ---------------------------------------------------------------------------
# (f) missing survey-crs -> clean actionable error, no traceback


def test_missing_survey_crs_clean_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "crs", None)  # simulate "not installed"
    csv_path = _geo_csv(tmp_path)
    out = str(tmp_path / "job.sfield.json")
    rc = main(["import", csv_path, "-o", out, "--target-crs", "EPSG:6539"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "pip install survey-crs" in captured.err
    assert not os.path.exists(out)


def test_reproject_api_missing_backend_message(monkeypatch):
    monkeypatch.setitem(sys.modules, "crs", None)
    with pytest.raises(CrsReprojectError, match="pip install survey-crs"):
        reproject_project(load_job_project(), "EPSG:6539")


def load_job_project():
    from field.models import Project
    return Project(name="empty")


# ---------------------------------------------------------------------------
# (e) v1 job files still read


def test_v1_job_file_still_reads():
    v1 = {
        "format": "survey-field/job",
        "schema_version": 1,
        "generator": "survey-field 0.1.0",
        "project": {
            "name": "v1job",
            "crs": "NAD83(2011) / UTM zone 18N",
            "source_files": ["day1.csv"],
            "base_stations": [],
            "sessions": [],
        },
    }
    project = load_job(v1)
    assert project.name == "v1job"
    assert project.crs_provenance is None
    # ... and it round-trips without gaining the new key.
    assert "crs_provenance" not in dump_job(project)["project"]


def test_v1_file_written_without_flag_reads_back(tmp_path):
    csv_path = _proj_csv(tmp_path, "NAD83(2011) / New York Long Island (ftUS)")
    out = str(tmp_path / "job.sfield.json")
    assert main(["import", csv_path, "-o", out]) == 0
    project = read_job(out)
    assert project.crs_provenance is None
    assert project.n_points() == 2


# ---------------------------------------------------------------------------
# build #2 adapter contract: to_adjust_control / to_adjust_observations keep
# returning plain data with the documented shapes


def test_adjust_adapter_contract_on_projected_job(tmp_path):
    csv_path = _proj_csv(tmp_path, "NAD83(2011) / New York Long Island (ftUS)")
    out = str(tmp_path / "job.sfield.json")
    assert main(["import", csv_path, "-o", out]) == 0
    project = read_job(out)
    fixed = to_adjust_control(project)
    assert fixed == {"BASE-1": pytest.approx(30.0)}
    obs = to_adjust_observations(project)
    assert len(obs) == 2
    for o in obs:
        assert set(o) == {"from_station", "to_station", "delta_h", "sigma",
                          "excluded_reason"}
    assert obs[0]["from_station"] == "BASE-1"
    assert obs[0]["to_station"] == "P1"
    assert obs[0]["delta_h"] == pytest.approx(28.554 - 30.0)
    assert obs[0]["sigma"] == pytest.approx(0.018)  # elevation RMS
    assert obs[0]["excluded_reason"] is None


def test_adjust_adapter_contract_on_reprojected_job(tmp_path):
    _need_crs()
    csv_path = _geo_csv(tmp_path)
    out = str(tmp_path / "job.sfield.json")
    assert main(["import", csv_path, "-o", out, "--target-crs", "EPSG:6539"]) == 0
    project = read_job(out)
    # Geographic export: no base elevations known -> empty control, no
    # observations, but the shapes are exactly the documented plain-data ones.
    assert to_adjust_control(project) == {}
    assert to_adjust_observations(project) == []
