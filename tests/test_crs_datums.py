"""Datum paths: every pair resolves, carries accuracy/source metadata,
and v1 approximations are explicitly flagged."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import crs


def test_same_datum_is_exact():
    for d in crs.DATUMS:
        p = crs.datum_path(d, d)
        assert p.is_exact
        assert p.accuracy_horizontal_m == 0.0


def test_all_pairs_resolve_with_metadata():
    for a in crs.DATUMS:
        for b in crs.DATUMS:
            p = crs.datum_path(a, b)
            assert p.from_datum == a and p.to_datum == b
            assert p.method in ("identity", "null-approximation")
            assert p.source, (a, b)
            assert p.region, (a, b)
            if not p.is_exact:
                assert p.accuracy_horizontal_m > 0, (a, b)
                assert p.warning, (a, b)  # approximations must warn


def test_nad83_2011_to_wgs84_accuracy():
    p = crs.datum_path("NAD83(2011)", "WGS 84 (G2296)")
    assert p.method == "null-approximation"
    assert p.accuracy_horizontal_m == pytest.approx(2.0)
    assert "geog862" in p.source  # Penn State source cited


def test_cors96_to_2011_is_centimetre_level():
    p = crs.datum_path("NAD83(CORS96)", "NAD83(2011)")
    assert p.accuracy_horizontal_m <= 0.05
    assert "2011" in p.source


def test_unknown_datum_raises():
    with pytest.raises(crs.DatumError):
        crs.datum_path("NAD27", "WGS 84 (G2296)")


def test_transform_result_carries_datum_provenance():
    r = crs.transform_coords(-76.86, 42.43, 4326, 6534)
    assert r.from_datum == "WGS 84 (G2296)"
    assert r.to_datum == "NAD83(2011)"
    assert not r.datum_path.is_exact
    assert any("datum" in w.lower() for w in r.warnings)
    assert r.backend in ("survey-geodesy", "internal")
