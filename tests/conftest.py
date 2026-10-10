"""Unified pytest fixtures and configurations for SurveySuite."""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
import pathlib
import socket
import sys
from typing import List, Optional

import pytest

# Ensure src/ is on sys.path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from adjustflow import stochastic
from linework.codeset import builtin_codeset
from linework.keys import DescriptionKeys, keys_template
from linework.prefixes import FigurePrefixDB, prefixes_template


# ==================== NGS / OPUS Etiquette ====================
@pytest.fixture(autouse=True)
def _block_non_localhost_connections(monkeypatch):
    """Hard guarantee: tests must never connect to live external servers."""
    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(
                f"blocked non-localhost connection to {host!r}: "
                "tests must never contact live NGS/OPUS endpoints"
            )
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


# ==================== Linework Stubs & Fixtures ====================
@dataclass
class StubPoint:
    name: str
    code: str = ""
    easting: Optional[float] = None
    northing: Optional[float] = None
    elevation: Optional[float] = None


@dataclass
class StubSession:
    points: List[StubPoint] = dc_field(default_factory=list)


@dataclass
class StubProject:
    name: str = "test-job"
    crs: str = ""
    sessions: List[StubSession] = dc_field(default_factory=list)


def P(name, code, e, n, h=None):
    return StubPoint(name=name, code=code, easting=e, northing=n, elevation=h)


@pytest.fixture()
def codeset():
    return builtin_codeset("emlid")


@pytest.fixture()
def keys():
    return DescriptionKeys.from_dict(keys_template())


@pytest.fixture()
def prefixes():
    return FigurePrefixDB.from_dict(prefixes_template())


@pytest.fixture()
def builder(codeset, keys, prefixes):
    from linework.figures import FigureBuilder
    return FigureBuilder(codeset, keys, prefixes)


# ==================== AdjustFlow Project Fixtures ====================
def make_point(name, easting, northing, elevation, rms=0.010,
               rms_u=0.015, solution="FIX", session_pts=None):
    from field.models import SurveyPoint
    return SurveyPoint(
        name=name, easting=easting, northing=northing, elevation=elevation,
        rms_e=rms, rms_n=rms, rms_u=rms_u, rms_lateral=rms * 1.4,
        solution=solution, antenna_height_m=2.0, samples=25, pdop=1.8,
        baseline_m=500.0)


def make_project():
    """Two sessions, three occupations of point 101, one of 102, one FLOAT."""
    from field.models import BaseStation, Project, RoverSession
    base = BaseStation(id="BASE-1", easting=500000.0, northing=4500000.0,
                       elevation=100.0, n_points=5)
    s1 = RoverSession(id="2026-09-25_BASE-1", base_station_id="BASE-1",
                      date="2026-09-25", points=[
                          make_point("101", 500100.00, 4500100.00, 105.00),
                          make_point("101", 500100.02, 4500099.99, 105.02),
                          make_point("102", 500200.00, 4500200.00, 110.00),
                      ])
    s2 = RoverSession(id="2026-09-26_BASE-1", base_station_id="BASE-1",
                      date="2026-09-26", points=[
                          make_point("101", 500099.99, 4500100.01, 104.99),
                          make_point("103", 500300.00, 4500300.00, 115.00,
                                     solution="FLOAT"),
                      ])
    return Project(name="test-job", crs="NAD83(2011) / UTM zone 18N",
                   source_files=["day1.csv", "day2.csv"],
                   base_stations=[base], sessions=[s1, s2])


@pytest.fixture
def project():
    return make_project()


@pytest.fixture
def cfg():
    return stochastic.default_weights()
