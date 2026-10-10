import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tiffmaker import make_tif
from basemap.tiff import TiffFile
from basemap.geo import (geotransform_from_ifd, parse_geokeys,
                         geokey_summary)
from basemap.crs import crs_from_ifd, ensure_crs_match
from basemap.errors import NoGeoreferencing, CRSMismatch


@pytest.fixture
def tmp_tif(tmp_path):
    def _mk(**kw):
        p = str(tmp_path / f"g{len(list(tmp_path.iterdir()))}.tif")
        return make_tif(p, **kw)
    return _mk


def test_scale_tiepoint_math(tmp_tif):
    # hand calc: origin (500000, 4000000), gsd 0.05, 64x48 px
    path, _ = tmp_tif(w=64, h=48)
    with TiffFile(path) as tf:
        gt = geotransform_from_ifd(tf.main_ifd, path)
    assert gt.gsd_x == pytest.approx(0.05)
    assert gt.gsd_y == pytest.approx(0.05)
    # pixel (0,0) is the outer corner of the top-left pixel
    assert gt.pixel_to_world(0, 0) == pytest.approx((500000.0, 4000000.0))
    assert gt.pixel_to_world(64, 48) == pytest.approx(
        (500000.0 + 64 * 0.05, 4000000.0 - 48 * 0.05))
    xmin, ymin, xmax, ymax = gt.extent(64, 48)
    assert (xmin, ymin, xmax, ymax) == pytest.approx(
        (500000.0, 4000000.0 - 48 * 0.05,
         500000.0 + 64 * 0.05, 4000000.0))
    # roundtrip
    c, r = gt.world_to_pixel(500001.0, 3999999.0)
    assert (c, r) == pytest.approx((20.0, 20.0))


def test_model_transformation(tmp_tif):
    # 30-degree rotated grid: x = ox + cos30*col*gsd - sin30*row*gsd ...
    import math
    gsd, ox, oy = 0.1, 1000.0, 2000.0
    th = math.radians(30)
    m = (math.cos(th) * gsd, -math.sin(th) * gsd, 0.0, ox,
         math.sin(th) * gsd, math.cos(th) * gsd, 0.0, oy,
         0.0, 0.0, 0.0, 0.0,
         0.0, 0.0, 0.0, 1.0)
    path, _ = tmp_tif(w=32, h=32, transform=m)
    with TiffFile(path) as tf:
        gt = geotransform_from_ifd(tf.main_ifd, path)
    assert gt.gsd_x == pytest.approx(gsd)
    assert gt.gsd_y == pytest.approx(gsd)
    assert not gt.is_north_up
    x, y = gt.pixel_to_world(10, 0)
    assert (x, y) == pytest.approx(
        (ox + 10 * gsd * math.cos(th), oy + 10 * gsd * math.sin(th)))
    # extent covers all four rotated corners
    xmin, ymin, xmax, ymax = gt.extent(32, 32)
    assert xmax - xmin > 32 * gsd  # rotation widens the bbox


def test_no_georef_raises(tmp_tif):
    path, _ = tmp_tif(georef=False)
    with TiffFile(path) as tf:
        with pytest.raises(NoGeoreferencing):
            geotransform_from_ifd(tf.main_ifd, path)


def test_geokeys_epsg(tmp_tif):
    path, _ = tmp_tif(epsg=32618)
    with TiffFile(path) as tf:
        keys = parse_geokeys(tf.main_ifd)
    assert keys[3072] == 32618
    assert keys[1024] == 1  # projected
    assert geokey_summary(keys) == "projected EPSG:32618"


def test_crs_from_ifd(tmp_tif):
    path, _ = tmp_tif(epsg=32618)
    with TiffFile(path) as tf:
        crs = crs_from_ifd(tf.main_ifd, path)
    assert crs.epsg == 32618
    assert crs.kind == "projected"
    assert "UTM zone 18N" in str(crs)
    assert crs.proj4.startswith("+proj=utm +zone=18")


def test_crs_no_geokeys(tmp_tif):
    path, _ = tmp_tif(georef=False)
    with TiffFile(path) as tf:
        with pytest.raises(NoGeoreferencing):
            crs_from_ifd(tf.main_ifd, path)


def test_ensure_crs_match_ok(tmp_tif):
    path, _ = tmp_tif(epsg=26918)
    with TiffFile(path) as tf:
        crs = crs_from_ifd(tf.main_ifd, path)
    assert ensure_crs_match(crs, "EPSG:26918", path) == 26918
    assert ensure_crs_match(crs, "NAD83 / UTM zone 18N (EPSG 26918)",
                            path) == 26918


def test_ensure_crs_mismatch_raises(tmp_tif):
    path, _ = tmp_tif(epsg=32618)  # WGS84 UTM 18N
    with TiffFile(path) as tf:
        crs = crs_from_ifd(tf.main_ifd, path)
    with pytest.raises(CRSMismatch) as ei:
        ensure_crs_match(crs, "EPSG:26918", path)  # NAD83 UTM 18N
    assert "mismatch" in str(ei.value).lower()


def test_ensure_crs_unparseable_project(tmp_tif):
    path, _ = tmp_tif(epsg=32618)
    with TiffFile(path) as tf:
        crs = crs_from_ifd(tf.main_ifd, path)
    with pytest.raises(CRSMismatch):
        ensure_crs_match(crs, "NAD83(2011) / UTM zone 18N", path)
