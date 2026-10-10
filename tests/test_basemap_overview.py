import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tiffmaker import make_tif
from basemap.raster import GeoTIFFRaster
from basemap.overview import (build_overviews, overview_info,
                              overview_levels_for)
from basemap.tiff import TiffFile


@pytest.fixture
def big_tif(tmp_path):
    p = str(tmp_path / "big.tif")
    path, _ = make_tif(p, w=512, h=384, tiled=True, tile_size=128,
                       compression=8)
    return path


def test_planned_levels():
    assert overview_levels_for(512, 384) == [(256, 192)]
    assert overview_levels_for(4096, 4096) == [
        (2048, 2048), (1024, 1024), (512, 512), (256, 256)]
    assert overview_levels_for(100, 100) == []


def test_build_and_read_back(big_tif):
    ovr = build_overviews(big_tif)
    assert ovr == big_tif + ".ovr"
    levels = overview_info(big_tif)
    assert len(levels) == 1
    assert (levels[0]["width"], levels[0]["height"]) == (256, 192)
    assert not levels[0]["internal"]
    # the sidecar is a plain multi-IFD TIFF any reader can open
    with TiffFile(ovr) as tf:
        assert tf.main_ifd.width == 256
    # and the raster picks it up as an overview
    with GeoTIFFRaster(big_tif) as r:
        assert len(r.overview_ifds) == 1
        rgb, w, h = r.render(max_px=300)
        assert max(w, h) <= 300


def test_overview_georef_scaled(big_tif):
    build_overviews(big_tif)
    with TiffFile(big_tif + ".ovr") as tf:
        ifd = tf.main_ifd
        sx, sy, _ = ifd.values(33550)
    # level is 256x192 from 512x384 -> 2x GSD
    assert sx == pytest.approx(0.10)
    assert sy == pytest.approx(0.10)


def test_render_uses_overview(big_tif):
    build_overviews(big_tif)
    with GeoTIFFRaster(big_tif) as r:
        # target 200px: overview (256px) covers it, main (512) is bigger
        rgb, w, h = r.render(max_px=200)
        assert (w, h) == (200, 150)
