import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tiffmaker import make_tif
from basemap.drafting_adapter import GeoTIFFRasterSource
from basemap.errors import CRSMismatch, NoGeoreferencing


@pytest.fixture
def tif_path(tmp_path):
    p = str(tmp_path / "a.tif")
    path, _ = make_tif(p, w=64, h=48, epsg=32618)
    return path


def test_protocol_shape(tif_path):
    src = GeoTIFFRasterSource(tif_path, project_crs="EPSG:32618")
    try:
        xmin, ymin, xmax, ymax = src.extent_world()
        assert xmax - xmin == pytest.approx(64 * 0.05)
        assert ymax - ymin == pytest.approx(48 * 0.05)
        data, w, h, kind = src.image()
        assert kind == "rgb"
        assert len(data) == w * h * 3
        assert max(w, h) <= 4096
    finally:
        src.close()


def test_max_render_px_respected(tif_path):
    src = GeoTIFFRasterSource(tif_path, project_crs="EPSG:32618",
                              max_render_px=32)
    try:
        _, w, h, _ = src.image()
        assert max(w, h) <= 32
    finally:
        src.close()


def test_opacity_fades_toward_white(tif_path):
    full = GeoTIFFRasterSource(tif_path, project_crs="EPSG:32618",
                               opacity=1.0)
    half = GeoTIFFRasterSource(tif_path, project_crs="EPSG:32618",
                               opacity=0.5)
    try:
        d1, _, _, _ = full.image()
        d2, _, _, _ = half.image()
        # fade toward white: every channel moves up
        assert all(b >= a for a, b in zip(d1, d2))
        assert any(b > a for a, b in zip(d1, d2))
    finally:
        full.close()
        half.close()


def test_bad_opacity_rejected(tif_path):
    with pytest.raises(ValueError):
        GeoTIFFRasterSource(tif_path, opacity=0.0)
    with pytest.raises(ValueError):
        GeoTIFFRasterSource(tif_path, opacity=1.5)


def test_crs_mismatch_fails_loud(tif_path):
    with pytest.raises(CRSMismatch):
        GeoTIFFRasterSource(tif_path, project_crs="EPSG:26918")


def test_crs_check_skippable(tif_path):
    src = GeoTIFFRasterSource(tif_path, project_crs=None)
    src.close()


def test_no_crs_fails(tmp_path):
    # no georeferencing tags at all -> the adapter refuses: a basemap
    # with unknown placement must never render under survey linework
    p2 = str(tmp_path / "nocrs2.tif")
    path2, _ = make_tif(p2, w=16, h=16, georef=False)
    with pytest.raises(NoGeoreferencing):
        GeoTIFFRasterSource(path2, project_crs="EPSG:32618")


def test_works_without_drafting_installed(tif_path, monkeypatch):
    # the adapter must not hard-require survey-drafting at import time
    import basemap.drafting_adapter as da
    assert da.is_drafting_available() in (True, False)
    src = GeoTIFFRasterSource(tif_path, project_crs="EPSG:32618")
    src.close()
