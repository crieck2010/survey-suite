import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tiffmaker import make_tif
from basemap.raster import GeoTIFFRaster


@pytest.fixture
def tmp_tif(tmp_path):
    def _mk(**kw):
        p = str(tmp_path / f"r{len(list(tmp_path.iterdir()))}.tif")
        return make_tif(p, **kw)
    return _mk


def _expected_rgb(pattern, w, h, x0=0, y0=0, x1=None, y1=None):
    x1 = w if x1 is None else x1
    y1 = h if y1 is None else y1
    out = bytearray()
    for y in range(y0, y1):
        for x in range(x0, x1):
            out += bytes(pattern(x, y))
    return bytes(out)


def test_full_read_matches_pattern(tmp_tif):
    path, pat = tmp_tif(w=64, h=48)
    with GeoTIFFRaster(path) as r:
        rgb, w, h = r.read_window(0, 0, 64, 48)
    assert (w, h) == (64, 48)
    assert rgb == _expected_rgb(pat, 64, 48)


def test_windowed_read_equals_crop(tmp_tif):
    path, pat = tmp_tif(w=64, h=48, tiled=True, tile_size=16,
                        rows_per_strip=16)
    with GeoTIFFRaster(path) as r:
        full, _, _ = r.read_window(0, 0, 64, 48)
        sub, w, h = r.read_window(10, 12, 50, 40)
    assert (w, h) == (40, 28)
    # crop the full read and compare
    expect = bytearray()
    for y in range(12, 40):
        expect += full[y * 64 * 3 + 10 * 3:y * 64 * 3 + 50 * 3]
    assert sub == bytes(expect)
    # windowed read only decodes intersecting tiles (9 of 12 here);
    # correctness above is the assertion that matters


def test_strip_vs_tile_equivalence(tmp_tif):
    p1, pat1 = tmp_tif(w=48, h=40, tiled=False)
    p2, _ = tmp_tif(w=48, h=40, tiled=True, tile_size=16,
                    pattern=lambda x, y: pat1(x, y))
    with GeoTIFFRaster(p1) as r1, GeoTIFFRaster(p2) as r2:
        a, _, _ = r1.read_window(0, 0, 48, 40)
        b, _, _ = r2.read_window(0, 0, 48, 40)
    assert a == b


@pytest.mark.parametrize("comp", [1, 5, 8, 32773])
def test_compressions(tmp_tif, comp):
    path, pat = tmp_tif(w=48, h=32, compression=comp)
    with GeoTIFFRaster(path) as r:
        rgb, _, _ = r.read_window(0, 0, 48, 32)
    assert rgb == _expected_rgb(pat, 48, 32)


@pytest.mark.parametrize("comp", [1, 5, 8])
def test_predictor(tmp_tif, comp):
    path, pat = tmp_tif(w=48, h=32, compression=comp, predictor=2)
    with GeoTIFFRaster(path) as r:
        rgb, _, _ = r.read_window(0, 0, 48, 32)
    assert rgb == _expected_rgb(pat, 48, 32)


def test_separate_planar(tmp_tif):
    path, pat = tmp_tif(w=40, h=32, planar=2, predictor=2, compression=8)
    with GeoTIFFRaster(path) as r:
        rgb, _, _ = r.read_window(0, 0, 40, 32)
    assert rgb == _expected_rgb(pat, 40, 32)


def test_16bit_scaling(tmp_tif):
    pat = lambda x, y: (x * 1000 + y * 37) % 65536
    path, _ = tmp_tif(w=32, h=24, kind="gray", bps=16, pattern=pat)
    with GeoTIFFRaster(path) as r:
        rgb, w, h = r.read_window(0, 0, 32, 24)
    assert (w, h) == (32, 24)
    # spot check the 16->8 mapping: v*255//65535 rounded
    v = pat(5, 3)
    expect = (v * 255 + 32768) // 65535
    o = (3 * 32 + 5) * 3
    assert rgb[o] == rgb[o + 1] == rgb[o + 2] == expect


def test_white_is_zero_inverts(tmp_tif):
    path, _ = tmp_tif(w=16, h=16, kind="gray", photometric=0,
                      pattern=lambda x, y: 200)
    with GeoTIFFRaster(path) as r:
        rgb, _, _ = r.read_window(0, 0, 16, 16)
    # tiffmaker pre-inverted the stored samples for photometric 0, so the
    # assembled output must be back at 200
    assert rgb[0] == 200


def test_rgba_composites_over_white(tmp_tif):
    def pat(x, y):
        return (255, 0, 0, 128)  # half-transparent red
    path, _ = tmp_tif(w=8, h=8, kind="rgba", pattern=pat)
    with GeoTIFFRaster(path) as r:
        rgb, _, _ = r.read_window(0, 0, 8, 8)
    # 255*0.5+255*0.5 = 255 red; 0*0.5+255*0.5 = 127 green/blue
    assert rgb[0] == 255
    assert rgb[1] == rgb[2] == 127


def test_nodata_masked_white(tmp_tif):
    def pat(x, y):
        return (10, 20, 30) if x < 8 else (0, 0, 0)
    path, _ = tmp_tif(w=16, h=8, pattern=pat, nodata=0)
    with GeoTIFFRaster(path) as r:
        assert r.nodata_fraction() == pytest.approx(0.5)
        rgb, _, _ = r.read_window(0, 0, 16, 8)
    assert rgb[0:3] == bytes((10, 20, 30))
    o = (0 * 16 + 10) * 3
    assert rgb[o:o + 3] == bytes((255, 255, 255))


def test_info_fields(tmp_tif):
    path, _ = tmp_tif(w=64, h=48, epsg=32618)
    with GeoTIFFRaster(path) as r:
        info = r.info()
    assert info["width"] == 64 and info["height"] == 48
    assert info["bands"] == 3
    assert info["compression"] == "none"
    assert "EPSG:32618" in info["crs"]
    assert info["gsd_x_m"] == pytest.approx(0.05)
    e = info["extent"]
    assert e["xmax"] - e["xmin"] == pytest.approx(64 * 0.05)


def test_render_caps_resolution(tmp_tif):
    path, _ = tmp_tif(w=200, h=100)
    with GeoTIFFRaster(path) as r:
        rgb, w, h = r.render(max_px=50)
    assert max(w, h) <= 50
    assert (w, h) == (50, 25)


def test_band_stats(tmp_tif):
    path, _ = tmp_tif(w=32, h=32,
                      pattern=lambda x, y: (x, y, 128))
    with GeoTIFFRaster(path) as r:
        stats = r.band_stats()
    assert stats[0]["min"] == 0 and stats[0]["max"] == 31
    assert stats[2]["min"] == stats[2]["max"] == 128
    assert stats[0]["mean"] == pytest.approx(15.5)
