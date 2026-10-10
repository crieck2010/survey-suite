"""Minimal PNG writer (8-bit RGB / gray), stdlib only.

Used by ``basemap thumb``. Not a general PNG library -- it writes what the
CLI needs: non-interlaced truecolor/grayscale PNGs with zlib compression
and Sub filtering.
"""

import struct
import zlib


def _chunk(ctype, data):
    out = struct.pack(">I", len(data)) + ctype + data
    out += struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    return out


def write_png(path, rgb, width, height, gray=False):
    """Write 8-bit PNG. ``rgb`` is row-major top-first bytes
    (3 bytes/px, or 1 byte/px when ``gray=True``)."""
    ch = 1 if gray else 3
    ctype = 0 if gray else 2
    raw = bytearray()
    for y in range(height):
        row = rgb[y * width * ch:(y + 1) * width * ch]
        raw.append(1)  # Sub filter
        prev = 0
        # Sub filter works per byte with x-ch lookback; do it byte-wise
        filt = bytearray(len(row))
        for i, b in enumerate(row):
            a = row[i - ch] if i >= ch else 0
            filt[i] = (b - a) & 0xFF
        raw += filt
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                             8, ctype, 0, 0, 0)))
        fh.write(_chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
        fh.write(_chunk(b"IEND", b""))
