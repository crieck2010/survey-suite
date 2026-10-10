import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tiffmaker import make_tif
from basemap.quality import check_scale, required_gsd, quality_report


def test_required_gsd_math():
    # 1" = 50' -> denominator 600 -> 0.25mm * 600 = 0.15 m
    assert required_gsd(600) == pytest.approx(0.15)


def test_check_scale_pass():
    chk = check_scale(0.05, "1\"=50'")
    assert chk["verdict"] == "PASS"
    assert chk["required_gsd_m"] == pytest.approx(0.15)


def test_check_scale_warn():
    # 30 cm imagery at 1"=50' (needs 15 cm) -> WARN, and it says why
    chk = check_scale(0.30, "1\"=50'")
    assert chk["verdict"] == "WARN"
    assert "soft" in chk["message"]


def test_check_scale_metric_label():
    chk = check_scale(0.10, "1:500")
    assert chk["required_gsd_m"] == pytest.approx(0.125)
    assert chk["verdict"] == "PASS"


def test_check_scale_unknown_label():
    with pytest.raises(ValueError):
        check_scale(0.05, "banana")


def test_quality_report(tmp_path):
    p = str(tmp_path / "q.tif")
    path, _ = make_tif(p, w=64, h=48, epsg=32618)
    rep = quality_report(path)
    assert rep["dimensions_px"] == (64, 48)
    assert rep["gsd_m"]["x"] == pytest.approx(0.05)
    assert "EPSG:32618" in rep["crs"]
    assert rep["nodata_fraction"] == 0.0
    assert len(rep["band_stats"]) == 3
    # 5 cm imagery passes both default scales
    assert all(c["verdict"] == "PASS" for c in rep["scale_checks"])
