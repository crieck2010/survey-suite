import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tiffmaker import make_tif
from basemap.cli import main
from basemap.png import write_png


def _tif(tmp_path):
    p = str(tmp_path / "c.tif")
    path, _ = make_tif(p, w=64, h=48, epsg=32618)
    return path


def test_cli_info(tmp_path, capsys):
    assert main(["info", _tif(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "EPSG:32618" in out
    assert "64 x 48" in out


def test_cli_info_json(tmp_path, capsys):
    assert main(["info", "--json", _tif(tmp_path)]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["width"] == 64


def test_cli_info_quality(tmp_path, capsys):
    assert main(["info", "--quality", _tif(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out


def test_cli_thumb(tmp_path):
    tif = _tif(tmp_path)
    out = str(tmp_path / "thumb.png")
    assert main(["thumb", tif, out, "--width", "100"]) == 0
    with open(out, "rb") as fh:
        assert fh.read(8) == b"\x89PNG\r\n\x1a\n"


def test_cli_overview(tmp_path, capsys):
    p = str(tmp_path / "o.tif")
    path, _ = make_tif(p, w=512, h=512, tiled=True)
    assert main(["overview", path]) == 0
    assert os.path.exists(path + ".ovr")
    assert "wrote" in capsys.readouterr().out


def test_cli_missing_file():
    assert main(["info", "/nope/missing.tif"]) == 2


def test_png_writer_roundtrip_shape(tmp_path):
    out = str(tmp_path / "t.png")
    write_png(out, bytes([10, 20, 30]) * 64, 8, 8)
    with open(out, "rb") as fh:
        sig = fh.read(8)
        body = fh.read()
    assert sig == b"\x89PNG\r\n\x1a\n"
    assert b"IHDR" in body and b"IDAT" in body and b"IEND" in body
