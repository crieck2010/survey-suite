import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tiffmaker import make_tif
from basemap.tiff import TiffFile, decompress, _decode_lzw, _encode_lzw, \
    _decode_packbits, _encode_packbits, undo_predictor
from basemap.errors import CorruptTiff, UnsupportedTiff


@pytest.fixture
def tmp_tif(tmp_path):
    def _mk(**kw):
        p = str(tmp_path / f"t{len(list(tmp_path.iterdir()))}.tif")
        return make_tif(p, **kw)
    return _mk


def test_header_and_ifd(tmp_tif):
    path, _ = tmp_tif(w=32, h=24)
    with TiffFile(path) as tf:
        assert tf.main_ifd.width == 32
        assert tf.main_ifd.height == 24
        assert tf.main_ifd.samples_per_pixel == 3
        assert not tf._big


def test_bigtiff(tmp_tif):
    path, _ = tmp_tif(w=16, h=16, bigtiff=True)
    with TiffFile(path) as tf:
        assert tf._big
        assert tf.main_ifd.width == 16


def test_bad_magic(tmp_path):
    p = str(tmp_path / "bad.tif")
    with open(p, "wb") as fh:
        fh.write(b"NOTATIFF....")
    with pytest.raises(CorruptTiff):
        TiffFile(p)


def test_truncated(tmp_path):
    p = str(tmp_path / "trunc.tif")
    with open(p, "wb") as fh:
        fh.write(b"II*\x00\x08\x00\x00\x00")  # header, IFD at 8, then EOF
    with pytest.raises(CorruptTiff):
        TiffFile(p)


def test_lzw_roundtrip():
    data = bytes((i * 7 + 3) % 256 for i in range(5000))
    assert _decode_lzw(_encode_lzw(data), "mem") == data


def test_lzw_clear_midstream():
    # highly repetitive then random forces table resets in the encoder
    data = bytes([9] * 3000) + bytes(range(256)) * 8
    assert _decode_lzw(_encode_lzw(data), "mem") == data


def test_packbits_roundtrip():
    data = bytes([5] * 100) + bytes(range(200)) + bytes([7] * 50)
    assert _decode_packbits(_encode_packbits(data)) == data


def test_predictor_roundtrip():
    w, h, spp = 16, 8, 3
    raw = bytes((x * 13 + y * 7 + s * 31) % 256
                for y in range(h) for x in range(w) for s in range(spp))
    from tiffmaker import _difference_encode
    enc = _difference_encode(raw, w, h, spp, 8)
    assert undo_predictor(enc, w, h, spp, 8) == raw


def test_jpeg_unsupported(tmp_tif):
    from basemap.raster import GeoTIFFRaster
    path, _ = tmp_tif()
    # rewrite compression tag to JPEG by patching the tag in place is
    # complex; instead check the decompress gate directly
    with pytest.raises(UnsupportedTiff):
        decompress(b"\xff\xd8", 7, path)
    # and the raster-level gate via a hand-made tag edit
    with TiffFile(path) as tf:
        ifd = tf.main_ifd
        ifd.tags[259] = (3, 1, (7,))
    # (tag edit above is on the parsed object only; GeoTIFFRaster re-reads,
    # so test the gate function instead)
    from basemap.raster import _check_supported
    with pytest.raises(UnsupportedTiff):
        _check_supported(ifd, path)


def test_unsupported_compression():
    with pytest.raises(UnsupportedTiff):
        decompress(b"data", 34925, "mem")  # LZMA


def test_strip_offsets_present(tmp_tif):
    path, _ = tmp_tif(w=32, h=32, rows_per_strip=16)
    with TiffFile(path) as tf:
        ifd = tf.main_ifd
        assert len(ifd.data_offsets()) == 2
        assert not ifd.is_tiled


def test_tile_layout(tmp_tif):
    path, _ = tmp_tif(w=40, h=40, tiled=True, tile_size=16)
    with TiffFile(path) as tf:
        ifd = tf.main_ifd
        assert ifd.is_tiled
        assert len(ifd.data_offsets()) == 9  # 3x3 tiles
