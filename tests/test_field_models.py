"""Tests for the canonical job model."""

from field.models import BaseStation, Project, RoverSession, SurveyPoint


def _point(name="1", **kw):
    base = dict(name=name, easting=100.0, northing=200.0, elevation=10.0)
    base.update(kw)
    return SurveyPoint(**base)


def test_point_position_predicates():
    assert _point().has_projected()
    assert not _point().has_geographic()
    geo = SurveyPoint(name="g", longitude=-77.0, latitude=43.0,
                      ellipsoidal_height=50.0)
    assert geo.has_geographic() and not geo.has_projected()
    assert geo.has_any_position()
    empty = SurveyPoint(name="e")
    assert not empty.has_any_position()


def test_project_round_trip():
    project = Project(
        name="job-7",
        crs="NAD83(2011) / UTM zone 18N",
        source_files=["a.csv"],
        base_stations=[BaseStation(id="BASE-1", easting=1.0, northing=2.0,
                                   elevation=3.0, n_points=2)],
        sessions=[RoverSession(id="2026-09-25_BASE-1", base_station_id="BASE-1",
                               date="2026-09-25",
                               points=[_point("1"), _point("2", code="EP")])],
    )
    clone = Project.from_dict(project.to_dict())
    assert clone.name == "job-7"
    assert clone.crs == "NAD83(2011) / UTM zone 18N"
    assert clone.n_points() == 2
    assert [p.name for p in clone.iter_points()] == ["1", "2"]
    assert clone.base_station("BASE-1").elevation == 3.0
    assert clone.base_station("NOPE") is None
    assert clone.sessions[0].points[1].code == "EP"


def test_point_round_trip_preserves_meta():
    p = _point(meta={"custom": "x"})
    assert SurveyPoint.from_dict(p.to_dict()).meta == {"custom": "x"}
