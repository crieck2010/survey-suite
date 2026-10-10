"""Cross-check the internal projection math against PROJ (reference
implementation of the EPSG definitions).

Requires pyproj; skipped when it is not installed so the suite stays
stdlib-only. This is a development-time audit, not a runtime dependency.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import crs

pyproj = pytest.importorskip("pyproj", reason="pyproj not installed")


def _check(epsg, lat, lon, tol=0.001):
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:6318", "EPSG:%d" % epsg, always_xy=True)
    exp_e, exp_n = tr.transform(lon, lat)
    r = crs.project(lat, lon, epsg)
    assert abs(r.x - exp_e) <= tol, (epsg, r.x - exp_e)
    assert abs(r.y - exp_n) <= tol, (epsg, r.y - exp_n)


def test_sample_tm_zones_vs_proj():
    for epsg, lat, lon in [(6534, 42.43, -76.86), (6421, 34.0, -118.3),
                           (6511, 38.5, -92.5)]:
        _check(epsg, lat, lon)


def test_sample_lcc_zones_vs_proj():
    for epsg, lat, lon in [(6538, 40.76, -73.2), (6478, 40.7, -111.8),
                           (6566, 18.2, -66.4)]:
        _check(epsg, lat, lon)


def test_hotine_vs_proj():
    _check(6394, 58.3, -134.4)


def test_sample_utm_vs_proj():
    r = crs.project(42.43, -76.86, 32618)
    tr = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
    exp_e, exp_n = tr.transform(-76.86, 42.43)
    # GRS80 (registry datum math) vs WGS84 (EPSG:4326) ellipsoids: sub-mm
    assert abs(r.x - exp_e) <= 0.002
    assert abs(r.y - exp_n) <= 0.002
