"""Tests for job validation."""

from field.models import BaseStation, Project, RoverSession, Solution, SurveyPoint
from field.validate import has_errors, validate_project


def _project(points, base_elev=100.0):
    base = BaseStation(id="BASE-1", easting=500000.0, northing=4500000.0,
                       elevation=base_elev)
    session = RoverSession(id="s1", base_station_id="BASE-1", date="2026-09-25",
                           points=points)
    return Project(name="t", base_stations=[base], sessions=[session])


def _fix(name="1", **kw):
    d = dict(name=name, easting=500001.0, northing=4500001.0, elevation=100.5,
             solution=Solution.FIX, rms_e=0.01, rms_n=0.01, rms_u=0.02,
             rms_lateral=0.014, antenna_height_m=2.0, samples=25, pdop=2.0,
             baseline_m=100.0)
    d.update(kw)
    return SurveyPoint(**d)


def test_clean_project_has_no_issues():
    assert validate_project(_project([_fix("1"), _fix("2")])) == []


def test_duplicate_names_are_errors():
    issues = validate_project(_project([_fix("1"), _fix("1")]))
    assert has_errors(issues)
    assert any(i.code == "duplicate-name" and i.severity == "error"
               for i in issues)


def test_point_without_position_is_error():
    issues = validate_project(_project([SurveyPoint(name="x")]))
    assert any(i.code == "no-position" and i.severity == "error" for i in issues)


def test_fix_without_base_is_error():
    project = Project(name="t", sessions=[
        RoverSession(id="s1", base_station_id=None, points=[_fix("1")])])
    issues = validate_project(project)
    assert any(i.code == "base-missing" and i.severity == "error" for i in issues)


def test_float_and_single_flagged():
    issues = validate_project(_project([
        _fix("1", solution=Solution.FLOAT, samples=5),
        _fix("2", solution=Solution.SINGLE),
    ]))
    codes = [(i.code, i.point_name) for i in issues if i.severity == "warning"]
    assert ("not-fixed", "1") in codes
    assert ("not-fixed", "2") in codes
    assert ("low-samples", "1") in codes
    assert not has_errors(issues)


def test_rms_thresholds():
    issues = validate_project(_project([
        _fix("1", rms_lateral=0.20, rms_u=0.30),
    ]))
    assert any(i.code == "rms-lateral" for i in issues)
    assert any(i.code == "rms-elev" for i in issues)


def test_missing_antenna_height():
    issues = validate_project(_project([_fix("1", antenna_height_m=None)]))
    assert any(i.code == "no-antenna-height" for i in issues)


def test_high_pdop_and_long_baseline():
    issues = validate_project(_project([
        _fix("1", pdop=8.5, baseline_m=25000.0),
    ]))
    assert any(i.code == "high-pdop" for i in issues)
    assert any(i.code == "long-baseline" for i in issues)


def test_thresholds_are_configurable():
    issues = validate_project(_project([_fix("1", rms_lateral=0.20)]),
                              rms_lateral_warn=0.50)
    assert not any(i.code == "rms-lateral" for i in issues)


def test_issue_string_format():
    issues = validate_project(_project([_fix("1"), _fix("1")]))
    s = str(issues[0])
    assert s.startswith("ERROR duplicate-name")
    assert "1" in s
