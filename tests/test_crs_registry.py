"""Registry integrity: every entry transforms, round-trips, and carries
researched EPSG parameters, units, and area of use."""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import crs
from crs import registry

REQUIRED_FIELDS = ("name epsg datum kind params params_epsg unit area_name "
                   "bbox state zone source_url notes group").split()


def test_registry_size_and_groups():
    entries = crs.list_entries()
    assert len(entries) == 345
    groups = crs.group_by_type()
    assert len(groups["spcs"]) == 222
    assert len(groups["utm"]) == 120
    assert len(groups["geographic"]) == 3


def test_every_entry_has_required_fields():
    for e in crs.list_entries():
        for f in REQUIRED_FIELDS:
            assert getattr(e, f, None) is not None or f in ("state", "zone", "notes"), \
                (e.epsg, f)
        assert e.source_url.startswith("https://epsg.io/%d" % e.epsg), e.epsg
        assert e.unit in ("m", "ftUS", "ft", "deg"), e.epsg
        assert e.datum in crs.DATUMS, e.epsg
        assert e.kind in ("tm", "lcc", "hotine", "utm", "geographic"), e.epsg
        assert len(e.bbox) == 4, e.epsg


def test_epsg_uniqueness_and_sort():
    codes = [e.epsg for e in crs.list_entries()]
    assert len(set(codes)) == len(codes)
    assert codes == sorted(codes)


def test_ny_epsg_codes():
    # Researched NY NAD83(2011) codes: Central 6534/6535, East 6536/6537,
    # Long Island 6538/6539, West 6540/6541.
    expect = {6534: "m", 6535: "ftUS", 6536: "m", 6537: "ftUS",
              6538: "m", 6539: "ftUS", 6540: "m", 6541: "ftUS"}
    for code, unit in expect.items():
        e = crs.by_epsg(code)
        assert e.unit == unit, code
        assert e.state == "New York", code
    zones = {e.zone for e in crs.zones_for_state("NY")}
    assert zones == {"Central", "East", "Long Island", "West"}


def test_ny_long_island_epsg_parameters():
    # Official EPSG:6538 parameters (https://epsg.io/6538), also defined in
    # NY Laws Chapter 605 (1995): parallels 41d02'/40d40', origin 40d10'N 74W.
    e = crs.by_epsg(6538)
    raw = {k: v["value"] for k, v in e.params_epsg.items()}
    assert e.kind == "lcc"
    assert raw["fe"] == 300000.0 and raw["fn"] == 0.0
    assert raw["lon0"] == -74.0
    assert abs(raw["lat0"] - 40.1666666666667) < 1e-9
    assert abs(raw["lat1"] - 41.0333333333333) < 1e-9
    assert abs(raw["lat2"] - 40.6666666666667) < 1e-9


def test_us_survey_foot_is_exact():
    assert crs.US_FOOT_M == 1200.0 / 3937.0
    # NY Central ftUS false easting converts to the metre definition
    m = crs.by_epsg(6534)
    f = crs.by_epsg(6535)
    assert abs(crs.ftus_to_m(f.params_epsg["fe"]["value"])
               - m.params_epsg["fe"]["value"]) < 2e-4


def test_wgs84_utm_codes():
    for z in (1, 18, 60):
        n = crs.by_epsg(32600 + z)
        s = crs.by_epsg(32700 + z)
        assert n.kind == "utm" and n.params["hemisphere"] == "N"
        assert s.kind == "utm" and s.params["hemisphere"] == "S"
        assert n.params["k0"] == 0.9996 and n.params["fe"] == 500000.0
        assert n.unit == "m" and s.unit == "m"


def test_geographic_entries():
    g2011 = crs.by_epsg(6318)
    gcors = crs.by_epsg(6783)
    wgs = crs.by_epsg(4326)
    assert (g2011.datum, gcors.datum, wgs.datum) == (
        "NAD83(2011)", "NAD83(CORS96)", "WGS 84 (G2296)")
    assert all(e.kind == "geographic" and e.unit == "deg"
               for e in (g2011, gcors, wgs))


def _center(e):
    w, s, ee, n = e.bbox
    lon = (w + ee) / 2
    # UTM south bboxes span -80..0; clamp test lat inside
    lat = min(max((s + n) / 2, -79.0), 83.0)
    return lat, lon


@pytest.mark.parametrize("entry", crs.list_entries(),
                         ids=[str(e.epsg) for e in crs.list_entries()])
def test_all_entries_round_trip(entry):
    """Every registry entry: project then unproject the bbox centre."""
    lat, lon = _center(entry)
    if entry.kind == "hotine":
        lat, lon = 57.5, -134.0  # inside Alaska zone 1
    r = crs.project(lat, lon, entry.epsg)
    b = crs.unproject(r.x, r.y, entry.epsg)
    tol = 1e-7  # ~1 cm
    assert abs(b.y - lat) <= tol, (entry.epsg, b.y - lat)
    assert abs(b.x - lon) <= tol or abs(abs(b.x - lon) - 360) <= tol, \
        (entry.epsg, b.x - lon)


def test_projected_projected_via_transform_coords():
    # NY Central m -> NY Central ftUS on the NB2147 position
    r = crs.transform_coords(226994.092, 270216.778, 6534, 6535)
    assert r.unit == "ftUS"
    assert abs(r.x - 744729.78) < 0.05
    assert abs(r.y - 886536.21) < 0.05
    assert r.datum_path.is_exact


def test_height_passthrough():
    r = crs.project(42.43, -76.86, 6534, h=192.564)
    assert r.h == 192.564
    b = crs.transform_coords(r.x, r.y, 6534, 4326, h=192.564)
    assert b.h == 192.564
