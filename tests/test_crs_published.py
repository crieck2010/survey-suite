"""Published-coordinate validations (millimetre level).

Each case cites its source. NGS datasheet values are published rounded to
0.001 m (0.01 ftUS), so assertions allow for source rounding plus numerical
projection error -- not exact equality.

Sources:
  - NB2147 / NB1891: NGS datasheets (retrieved live 2026-09-27 from
    https://www.ngs.noaa.gov/cgi-bin/ds_mark.prl?PidBox=<PID>);
    NAD83(2011) positions are ADJUSTED.
  - DI0446 (CENTRAL ISLIP CORS ARP, NYCI): NGS datasheet, NAD83(2011)
    ADJUSTED position.
  - NB2147 UTM 18N: NOAA-hosted Seneca NY Watershed LiDAR Survey Report
    (Northrop Grumman), control table p. 5:
    https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/9066/supplemental/Seneca_NY_Watershed_LiDAR_Survey_Report.pdf
    NOTE: this checks the UTM *projection math*. project() is fed the
    published lat/lon numbers directly; the ~1-2 m NAD83(2011)/WGS 84 frame
    difference is not exercised here, only the GRS80-vs-WGS84 ellipsoid
    difference in the formulas, which is sub-millimetre.
  - Alaska zone 1 (EPSG:6394, Hotine Oblique Mercator): reference values
    computed 2026-09-27 with PROJ (pyproj 3.8.0) from EPSG:6394, i.e. the
    reference implementation of the EPSG definition. No NGS-published
    SPCS values for this zone were available.
"""
from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import crs


def dms(d, m, s):
    return d + m / 60.0 + s / 3600.0


# (label, lat, lon, epsg, expected E, expected N, tolerance in CRS unit)
PUBLISHED = [
    ("NB2147 NY Central (m)",
     dms(42, 25, 58.52091), -dms(76, 51, 46.55757), 6534,
     226994.092, 270216.778, 0.0015),
    ("NB2147 NY Central (ftUS)",
     dms(42, 25, 58.52091), -dms(76, 51, 46.55757), 6535,
     744729.78, 886536.21, 0.02),
    ("NB1891 NY West (m)",
     dms(42, 32, 7.44358), -dms(77, 29, 17.91926), 6540,
     439953.828, 282142.939, 0.0015),
    ("NB1891 NY West (ftUS)",
     dms(42, 32, 7.44358), -dms(77, 29, 17.91926), 6541,
     1443415.18, 925663.96, 0.02),
    ("DI0446 NY Long Island (m)",
     dms(40, 45, 38.23676), -dms(73, 11, 51.78749), 6538,
     367742.490, 66266.506, 0.0015),
    ("DI0446 NY Long Island (ftUS)",
     dms(40, 45, 38.23676), -dms(73, 11, 51.78749), 6539,
     1206501.82, 217409.36, 0.02),
    ("NB2147 UTM 18N (m, projection math)",
     dms(42, 25, 58.52091), -dms(76, 51, 46.55757), 32618,
     346764.059, 4699526.108, 0.002),
]

# (lat, lon, expected E, expected N) from PROJ/EPSG:6394
HOTINE_REF = [
    (58.2999, -134.4199, 774505.600, 720099.875),
    (57.0, -133.6667, 818674.709, 575097.689),
    (55.5, -132.0, 923996.525, 409373.474),
    (59.0, -136.0, 684573.538, 800134.962),
]


@pytest.mark.parametrize("label,lat,lon,epsg,exp_e,exp_n,tol", PUBLISHED,
                         ids=[p[0] for p in PUBLISHED])
def test_published_forward(label, lat, lon, epsg, exp_e, exp_n, tol):
    r = crs.project(lat, lon, epsg)
    assert abs(r.x - exp_e) <= tol, "%s: dE=%r" % (label, r.x - exp_e)
    assert abs(r.y - exp_n) <= tol, "%s: dN=%r" % (label, r.y - exp_n)


@pytest.mark.parametrize("label,lat,lon,epsg,exp_e,exp_n,tol", PUBLISHED,
                         ids=[p[0] for p in PUBLISHED])
def test_published_inverse(label, lat, lon, epsg, exp_e, exp_n, tol):
    r = crs.unproject(exp_e, exp_n, epsg)
    # 1e-7 deg ~ 1.1 cm; published inputs are rounded so allow ~2 cm
    assert abs(r.y - lat) <= 2.5e-7, "%s: dlat=%r" % (label, r.y - lat)
    assert abs(r.x - lon) <= 2.5e-7, "%s: dlon=%r" % (label, r.x - lon)


@pytest.mark.parametrize("lat,lon,exp_e,exp_n", HOTINE_REF)
def test_hotine_alaska_zone1_vs_proj(lat, lon, exp_e, exp_n):
    r = crs.project(lat, lon, 6394)
    assert abs(r.x - exp_e) <= 0.002
    assert abs(r.y - exp_n) <= 0.002
    b = crs.unproject(r.x, r.y, 6394)
    assert abs(b.y - lat) < 1e-9
    assert abs(b.x - lon) < 1e-9
