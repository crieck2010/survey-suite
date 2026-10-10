"""Unit conversions, including the exact US survey foot (1200/3937 m)."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import crs


def test_us_foot_exact_definition():
    assert crs.US_FOOT_M == 1200.0 / 3937.0
    assert crs.m_to_ftus(1.0) == 3937.0 / 1200.0
    assert crs.ftus_to_m(3937.0) == pytest.approx(1200.0)


def test_round_trip():
    for v in (0.0, 1.0, 226994.092, 1007121.3424):
        assert crs.ftus_to_m(crs.m_to_ftus(v)) == pytest.approx(v)
        assert crs.ft_to_m(crs.m_to_ft(v)) == pytest.approx(v)


def test_international_foot():
    assert crs.m_to_ft(0.3048) == pytest.approx(1.0)
    assert crs.ft_to_m(1.0) == pytest.approx(0.3048)


def test_to_from_metres_dispatch():
    assert crs.to_metres(10.0, "m") == 10.0
    assert crs.to_metres(3937.0, "ftUS") == pytest.approx(1200.0)
    assert crs.from_metres(1200.0, "ftUS") == pytest.approx(3937.0)
    with pytest.raises(ValueError):
        crs.to_metres(1.0, "furlong")
