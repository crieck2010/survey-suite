"""Tests for the survey-adjust / survey-cogo adapters."""

import os

import pytest

from field.adapters import (
    job_summary,
    project_cogo_points,
    to_adjust_control,
    to_adjust_observations,
    to_cogo_kwargs,
)
from field.emlid import import_emlid_csv
from field.models import Solution, SurveyPoint

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples",
                       "demo_emlid_flow.csv")


@pytest.fixture()
def project():
    return import_emlid_csv(EXAMPLE)


def test_to_cogo_kwargs_shape(project):
    point = next(project.iter_points())
    kwargs = to_cogo_kwargs(point)
    assert kwargs is not None
    assert set(kwargs) == {"northing", "easting", "name", "elevation"}
    # splats straight into cogo.Point(northing, easting, name, elevation)
    assert kwargs["name"] == "101"
    assert kwargs["northing"] == pytest.approx(4780012.884)


def test_to_cogo_kwargs_none_for_geographic_only():
    p = SurveyPoint(name="g", longitude=-77.0, latitude=43.0,
                    ellipsoidal_height=50.0)
    assert to_cogo_kwargs(p) is None
    assert project_cogo_points.__doc__  # documented behaviour


def test_project_cogo_points(project):
    pts = project_cogo_points(project)
    assert len(pts) == 11  # all demo points are projected


def test_to_adjust_control(project):
    fixed = to_adjust_control(project)
    assert set(fixed) == {"BASE-1", "BASE-2"}
    assert fixed["BASE-1"] == pytest.approx(172.5)


def test_to_adjust_observations(project):
    obs = to_adjust_observations(project)
    # only FIX points with elevations; FLOAT(107)/SINGLE(108) excluded
    names = {o["to_station"] for o in obs}
    assert "107" not in names and "108" not in names
    assert len(obs) == 9
    o101 = next(o for o in obs if o["to_station"] == "101")
    assert o101["from_station"] == "BASE-1"
    assert o101["delta_h"] == pytest.approx(170.214 - 172.5)
    assert o101["sigma"] == pytest.approx(0.018)  # from elevation RMS
    assert set(o101) >= {"from_station", "to_station", "delta_h", "sigma"}
    # splats into adjust.DiffObservation(from_station, to_station, delta_h, sigma)
    for o in obs:
        assert o["sigma"] > 0


def test_job_summary(project):
    s = job_summary(project)
    assert s["n_points"] == 11
    assert s["n_base_stations"] == 2
    assert s["n_sessions"] == 2
    assert s["solutions"] == {Solution.FIX: 9, Solution.FLOAT: 1,
                              Solution.SINGLE: 1}
    assert s["n_projected"] == 11
