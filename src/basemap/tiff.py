"""Hand-rolled TIFF / BigTIFF reader and minimal writer, stdlib only.

The reader parses the header, every top-level IFD (following the next-IFD
chain), and SubIFDs (tag 330, where internal overviews live). It decodes
strip/tile sample data for the compressions this engine supports and fails
loud on everything else.

Supported in v1:
  - Classic TIFF and BigTIFF (magic 42 / 43)
  - Strip and tile organization
  - BitsPerSample 8 / 16, SampleFormat unsigned int
  - SamplesPerPixel 1 / 3 / 4 (gray / RGB / RGBA)
  - PhotometricInterpretation 0 (WhiteIsZero), 1 (BlackIsZero), 2 (RGB)
  - PlanarConfiguration 1 (contiguous) and 2 (separate)
  - Compression 1 (none), 5 (LZW), 8/32946 (Deflate), 32773 (PackBits)
  - Predictor 1 (none) and 2 (horizontal differencing)

Deliberately unsupported (fail loud): JPEG-in-TIFF, float samples,
CMYK / YCbCr photometrics, JBIG, LZMA, WebP.

The writer exists to (a) let the test suite generate synthetic GeoTIFFs
without any third-party library, and (b) write ``.ovr`` overview sidecars
as standard multi-IFD TIFFs any GDAL-based tool can also read.
"""

import struct
import zlib

from .errors import CorruptTiff, UnsupportedTiff

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------
TAG_IMAGE_WIDTH = 256
TAG_IMAGE_LENGTH = 257
TAG_BITS_PER_SAMPLE = 258
TAG_COMPRESSION = 259
TAG_PHOTOMETRIC = 262
TAG_STRIP_OFFSETS = 273
TAG_SAMPLES_PER_PIXEL = 277
TAG_ROWS_PER_STRIP = 278
TAG_STRIP_BYTE_COUNTS = 279
TAG_PLANAR_CONFIG = 284
TAG_PREDICTOR = 317
TAG_TILE_WIDTH = 322
TAG_TILE_LENGTH = 323
TAG_TILE_OFFSETS = 324
TAG_TILE_BYTE_COUNTS = 325
TAG_EXTRA_SAMPLES = 338
TAG_SAMPLE_FORMAT = 339
TAG_SUB_IFD = 330
TAG_MODEL_PIXEL_SCALE = 33550
TAG_MODEL_TIEPOINT = 33922
TAG_MODEL_TRANSFORMATION = 34264
TAG_GEO_KEY_DIRECTORY = 34735
TAG_GEO_DOUBLE_PARAMS = 34736
TAG_GEO_ASCII_PARAMS = 34737
TAG_GDAL_NODATA = 42113

COMPRESSION_NAMES = {
    1: "none", 5: "LZW", 6: "JPEG-old", 7: "JPEG",
    8: "deflate", 32773: "packbits", 32946: "deflate",
    34925: "LZMA", 50000: "ZSTD", 50001: "WebP",
}

# TIFF field types: type -> (struct char, size in bytes)
_FIELD_TYPES = {
    1: ("B", 1),    # BYTE
    2: ("c", 1),    # ASCII
    3: ("H", 2),    # SHORT
    4: ("I", 4),    # LONG
    5: ("II", 8),   # RATIONAL (pair of LONG)
    6: ("b", 1),    # SBYTE
    7: ("B", 1),    # UNDEFINED
    8: ("h", 2),    # SSHORT
    9: ("i", 4),    # SLONG
    10: ("ii", 8),  # SRATIONAL
    11: ("f", 4),   # FLOAT
    12: ("d", 8),   # DOUBLE
    16: ("Q", 8),   # LONG8
    17: ("q", 8),   # SLONG8
    18: ("Q", 8),   # IFD8
}


# ---------------------------------------------------------------------------
# IFD
# ---------------------------------------------------------------------------
class IFD:
    """One parsed Image File Directory.

    ``tags`` maps tag id -> (field_type, count, values). ``values`` is a
    tuple; RATIONAL/SRATIONAL values are decoded to float.
    """

    def __init__(self, tags, is_subifd=False):
        self.tags = tags
        self.is_subifd = is_subifd

    def has(self, tag):
        return tag in self.tags

    def values(self, tag, default=None):
        entry = self.tags.get(tag)
        return entry[2] if entry is not None else default

    def scalar(self, tag, default=None):
        vals = self.values(tag)
        if vals is None:
            return default
        return vals[0]

    # -- convenience accessors ------------------------------------------------
    @property
    def width(self):
        return self.scalar(TAG_IMAGE_WIDTH)

    @property
    def height(self):
        return self.scalar(TAG_IMAGE_LENGTH)

    @property
    def samples_per_pixel(self):
        return self.scalar(TAG_SAMPLES_PER_PIXEL, 1)

    @property
    def bits_per_sample(self):
        vals = self.values(TAG_BITS_PER_SAMPLE)
        if vals is None:
            return (1,)
        return tuple(vals)

    @property
    def compression(self):
        return self.scalar(TAG_COMPRESSION, 1)

    @property
    def photometric(self):
        return self.scalar(TAG_PHOTOMETRIC, 1)

    @property
    def planar(self):
        return self.scalar(TAG_PLANAR_CONFIG, 1)

    @property
    def predictor(self):
        return self.scalar(TAG_PREDICTOR, 1)

    @property
    def sample_format(self):
        vals = self.values(TAG_SAMPLE_FORMAT)
        if vals is None:
            return (1,) * self.samples_per_pixel
        return tuple(vals)

    @property
    def is_tiled(self):
        return self.has(TAG_TILE_OFFSETS)

    def data_offsets(self):
        if self.is_tiled:
            return self.values(TAG_TILE_OFFSETS, ())
        return self.values(TAG_STRIP_OFFSETS, ())

    def data_byte_counts(self):
        if self.is_tiled:
            return self.values(TAG_TILE_BYTE_COUNTS, ())
        return self.values(TAG_STRIP_BYTE_COUNTS, ())

    def pixel_count(self):
        w, h = self.width, self.height
        return (w or 0) * (h or 0)


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------
class TiffFile:
    """A parsed TIFF file. Keeps the file handle open for on-demand
    strip/tile reads (multi-GB orthomosaics are never fully loaded).

    Use as a context manager or call :meth:`close`.
    """

    def __init__(self, path):
        self.path = path
        try:
            self._fh = open(path, "rb")
        except OSError as exc:
            raise CorruptTiff(f"{path}: cannot open: {exc}") from exc
        try:
            self._parse_header()
            self.ifds = []
            self._parse_ifd_chain(self._first_ifd_offset, is_subifd=False)
        except Exception:
            self._fh.close()
            raise

    # -- context manager ------------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        fh, self._fh = self._fh, None
        if fh is not None:
            fh.close()

    # -- low-level IO ----------------------------------------------------------
    def _read_at(self, offset, n):
        if offset < 0:
            raise CorruptTiff(f"{self.path}: negative file offset {offset}")
        self._fh.seek(offset)
        data = self._fh.read(n)
        if len(data) != n:
            raise CorruptTiff(
                f"{self.path}: truncated file -- wanted {n} bytes at "
                f"offset {offset}, got {len(data)}"
            )
        return data

    # -- header ----------------------------------------------------------------
    def _parse_header(self):
        sig = self._read_at(0, 8)
        byte_order = sig[:2]
        if byte_order == b"II":
            self._endian = "<"
        elif byte_order == b"MM":
            self._endian = ">"
        else:
            raise CorruptTiff(
                f"{self.path}: not a TIFF file (bad byte-order mark)"
            )
        magic = struct.unpack(self._endian + "H", sig[2:4])[0]
        if magic == 42:
            self._big = False
            self._off_size = 4
            self._first_ifd_offset = struct.unpack(
                self._endian + "I", sig[4:8])[0]
        elif magic == 43:
            self._big = True
            off_bytes = struct.unpack(self._endian + "H", sig[4:6])[0]
            if off_bytes != 8:
                raise UnsupportedTiff(
                    f"{self.path}: BigTIFF with offset size {off_bytes} "
                    f"(only 8 supported)"
                )
            self._off_size = 8
            # sig[6:8] is a reserved zero word; first IFD offset follows
            self._first_ifd_offset = struct.unpack(
                self._endian + "Q", self._read_at(8, 8))[0]
        else:
            raise CorruptTiff(
                f"{self.path}: not a TIFF file (bad magic {magic})"
            )

    # -- IFD parsing -------------------------------------------------------------
    def _parse_ifd_chain(self, offset, is_subifd):
        seen = set()
        while offset:
            if offset in seen:
                raise CorruptTiff(
                    f"{self.path}: IFD offset loop at {offset}")
            seen.add(offset)
            ifd, next_offset = self._parse_ifd(offset, is_subifd)
            self.ifds.append(ifd)
            # SubIFDs (internal overviews / masks) hang off tag 330
            for sub_off in ifd.values(TAG_SUB_IFD, ()):
                self._parse_ifd_chain(sub_off, is_subifd=True)
            offset = next_offset

    def _parse_ifd(self, offset, is_subifd):
        e = self._endian
        if self._big:
            count = struct.unpack(e + "Q", self._read_at(offset, 8))[0]
            entry_size, off_fmt = 20, "Q"
            pos = offset + 8
        else:
            count = struct.unpack(e + "H", self._read_at(offset, 2))[0]
            entry_size, off_fmt = 12, "I"
            pos = offset + 2
        if count > 100000:
            raise CorruptTiff(
                f"{self.path}: absurd IFD entry count {count} at {offset}")
        tags = {}
        for _ in range(count):
            raw = self._read_at(pos, entry_size)
            pos += entry_size
            tag = struct.unpack(e + "H", raw[0:2])[0]
            ftype = struct.unpack(e + "H", raw[2:4])[0]
            if self._big:
                cnt = struct.unpack(e + "Q", raw[4:12])[0]
                val_field = raw[12:20]
            else:
                cnt = struct.unpack(e + "I", raw[4:8])[0]
                val_field = raw[8:12]
            tags[tag] = self._decode_entry(tag, ftype, cnt, val_field)
        next_offset = struct.unpack(
            e + off_fmt, self._read_at(pos, self._off_size))[0]
        return IFD(tags, is_subifd=is_subifd), next_offset

    def _decode_entry(self, tag, ftype, count, val_field):
        info = _FIELD_TYPES.get(ftype)
        if info is None:
            raise CorruptTiff(
                f"{self.path}: tag {tag}: unknown field type {ftype}")
        char, size = info
        total = size * count
        if total <= len(val_field):
            raw = val_field[:total]
        else:
            data_off = struct.unpack(
                self._endian + ("Q" if self._big else "I"), val_field)[0]
            raw = self._read_at(data_off, total)
        e = self._endian
        if ftype == 2:  # ASCII
            text = raw.split(b"\x00")[0].decode("ascii", errors="replace")
            return (ftype, count, (text,))
        if ftype in (5, 10):  # rationals -> float
            vals = []
            for i in range(count):
                num, den = struct.unpack(e + char, raw[i * 8:(i + 1) * 8])
                vals.append(num / den if den else 0.0)
            return (ftype, count, tuple(vals))
        if ftype == 7:  # UNDEFINED -> raw bytes
            return (ftype, count, (bytes(raw),))
        n = total // size
        vals = struct.unpack(e + char * n, raw[:n * size])
        return (ftype, count, vals)

    # -- IFD selection -------------------------------------------------------------
    @property
    def main_ifd(self):
        mains = [i for i in self.ifds if not i.is_subifd]
        if not mains:
            raise CorruptTiff(f"{self.path}: no image IFD found")
        return max(mains, key=lambda i: i.pixel_count())

    @property
    def overview_ifds(self):
        """Smaller IFDs usable as pyramid levels (internal overviews)."""
        main = self.main_ifd
        cands = [i for i in self.ifds
                 if i is not main and i.pixel_count() < main.pixel_count()
                 and i.width and i.height]
        return sorted(cands, key=lambda i: i.pixel_count(), reverse=True)

    # -- strip/tile data -------------------------------------------------------------
    def read_block(self, ifd, index):
        """Raw (still compressed) bytes of strip/tile ``index``."""
        offsets = ifd.data_offsets()
        counts = ifd.data_byte_counts()
        if not offsets or index >= len(offsets):
            raise CorruptTiff(
                f"{self.path}: block index {index} out of range "
                f"({len(offsets)} blocks)")
        n = counts[index] if index < len(counts) else None
        if n is None:
            # Byte count missing: read to EOF (last resort, documented)
            self._fh.seek(0, 2)
            n = self._fh.tell() - offsets[index]
        return self._read_at(offsets[index], n)


# ---------------------------------------------------------------------------
# Decompression
# ---------------------------------------------------------------------------
def decompress(data, compression, path="<memory>"):
    """Decompress one strip/tile payload. Returns raw bytes."""
    if compression == 1:
        return data
    if compression == 5:
        return _decode_lzw(data, path)
    if compression in (8, 32946):
        try:
            return zlib.decompress(data)
        except zlib.error as exc:
            raise CorruptTiff(
                f"{path}: deflate payload failed to decompress: {exc}"
            ) from exc
    if compression == 32773:
        return _decode_packbits(data)
    name = COMPRESSION_NAMES.get(compression, str(compression))
    raise UnsupportedTiff(
        f"{path}: compression {name} ({compression}) is not supported in "
        f"v1 -- re-export with None/LZW/Deflate/PackBits"
    )


def _decode_packbits(data):
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        header = data[i]
        i += 1
        if header > 127:
            header -= 256  # signed
        if 0 <= header <= 127:
            out += data[i:i + header + 1]
            i += header + 1
        elif -127 <= header <= -1:
            if i >= n:
                raise CorruptTiff("packbits stream truncated")
            out += bytes([data[i]]) * (1 - header)
            i += 1
        # header == -128: no-op
    return bytes(out)


def _decode_lzw(data, path):
    """TIFF variant LZW (early-change, MSB-first)."""
    CLEAR, EOI = 256, 257

    def bit_reader():
        buf, bits = 0, 0
        for byte in data:
            buf = (buf << 8) | byte
            bits += 8
            while bits >= width[0]:
                bits -= width[0]
                yield (buf >> bits) & ((1 << width[0]) - 1)
                buf &= (1 << bits) - 1

    width = [9]
    out = bytearray()
    table = {}
    prev = None

    def reset():
        table.clear()
        for i in range(256):
            table[i] = bytes([i])
        width[0] = 9
        return 258

    next_code = reset()
    for code in bit_reader():
        if code == CLEAR:
            next_code = reset()
            prev = None
            continue
        if code == EOI:
            break
        if code in table:
            entry = table[code]
        elif code == next_code and prev is not None:
            entry = prev + prev[:1]
        else:
            raise CorruptTiff(
                f"{path}: invalid LZW code {code} (table size {next_code})")
        out += entry
        if prev is not None:
            table[next_code] = prev + entry[:1]
            next_code += 1
            # TIFF "early change": the code width grows when the table
            # reaches 2**width - 1, one code sooner than the GIF variant.
            if next_code >= (1 << width[0]) - 1 and width[0] < 12:
                width[0] += 1
        prev = entry
    return bytes(out)


# ---------------------------------------------------------------------------
# Predictor
# ---------------------------------------------------------------------------
def undo_predictor(buf, width, height, spp, bps):
    """Undo horizontal differencing (Predictor tag = 2). In place."""
    if bps == 8:
        a = bytearray(buf)
        step = spp
        for y in range(height):
            base = y * width * step
            for x in range(1, width):
                o = base + x * step
                p = o - step
                for s in range(spp):
                    a[o + s] = (a[o + s] + a[p + s]) & 0xFF
        return bytes(a)
    if bps == 16:
        n = width * height * spp
        vals = list(struct.unpack("<%dH" % n, buf[:n * 2]))
        for y in range(height):
            base = y * width * spp
            for x in range(1, width):
                o = base + x * spp
                p = o - spp
                for s in range(spp):
                    vals[o + s] = (vals[o + s] + vals[p + s]) & 0xFFFF
        return struct.pack("<%dH" % n, *vals)
    raise UnsupportedTiff(
        f"horizontal predictor with {bps}-bit samples is not supported")


# ---------------------------------------------------------------------------
# Minimal TIFF writer (tests + .ovr sidecars)
# ---------------------------------------------------------------------------
def write_tiff(path, ifds, bigtiff=False):
    """Write a TIFF file.

    ``ifds`` is a list of ``(tags, blocks)`` where ``tags`` maps tag id ->
    value (int, float, str, or tuple/list of numbers) and ``blocks`` is a
    list of ``(raw_bytes, compression)`` payloads. Strip or tile layout is
    chosen from the tags: tile tags -> TileOffsets/TileByteCounts, else
    StripOffsets/StripByteCounts (+ RowsPerStrip).

    This is intentionally minimal -- it writes what this engine's reader
    (and GDAL) can read, nothing more.
    """
    endian = "<"  # always little-endian output
    is_tiled = TAG_TILE_WIDTH in ifds[0][0]

    with open(path, "w+b") as fh:
        # header
        if bigtiff:
            fh.write(b"II" + struct.pack("<H", 43)
                     + struct.pack("<H", 8) + struct.pack("<H", 0))
            first_ifd_ptr_at = fh.tell()
            fh.write(struct.pack("<Q", 0))  # placeholder
        else:
            fh.write(b"II" + struct.pack("<H", 42))
            first_ifd_ptr_at = fh.tell()
            fh.write(struct.pack("<I", 0))  # placeholder

        ifd_offsets = []
        for tags, blocks in ifds:
            tags = dict(tags)
            # compress payloads now so byte counts are known
            payloads = [_compress_block(raw, comp) for raw, comp in blocks]
            # write payload data
            offsets = []
            for p in payloads:
                offsets.append(fh.tell())
                fh.write(p)
            counts = [len(p) for p in payloads]
            if is_tiled:
                tags[TAG_TILE_OFFSETS] = offsets
                tags[TAG_TILE_BYTE_COUNTS] = counts
            else:
                tags[TAG_STRIP_OFFSETS] = offsets
                tags[TAG_STRIP_BYTE_COUNTS] = counts
                tags.setdefault(TAG_ROWS_PER_STRIP, 2 ** 32 - 1)

            ifd_offsets.append(fh.tell())
            _write_ifd(fh, tags, bigtiff, endian)

        # link IFDs
        for i, off in enumerate(ifd_offsets):
            nxt = ifd_offsets[i + 1] if i + 1 < len(ifd_offsets) else 0
            _write_next(fh, off, nxt, bigtiff, endian)
        # patch header's first-IFD pointer
        here = fh.tell()
        fh.seek(first_ifd_ptr_at)
        fh.write(struct.pack("<Q" if bigtiff else "<I", ifd_offsets[0]))
        fh.seek(here)


def _compress_block(raw, comp):
    if comp in (1, None):
        return raw
    if comp == 5:
        return _encode_lzw(raw)
    if comp in (8, 32946):
        return zlib.compress(raw)
    if comp == 32773:
        return _encode_packbits(raw)
    raise UnsupportedTiff(f"writer: compression {comp} not supported")


def _write_next(fh, ifd_off, nxt, bigtiff, endian):
    # next-IFD pointer sits right after the entries; find it by re-reading
    # the entry count we just wrote.
    fh.seek(ifd_off)
    if bigtiff:
        count = struct.unpack("<Q", fh.read(8))[0]
        pos = ifd_off + 8 + count * 20
        fh.seek(pos)
        fh.write(struct.pack("<Q", nxt))
    else:
        count = struct.unpack("<H", fh.read(2))[0]
        pos = ifd_off + 2 + count * 12
        fh.seek(pos)
        fh.write(struct.pack("<I", nxt))


def _tiff_field_type(value):
    if isinstance(value, str):
        return 2
    if isinstance(value, float):
        return 12
    vals = value if isinstance(value, (list, tuple)) else (value,)
    if any(isinstance(v, float) for v in vals):
        return 12
    mx = max(vals) if vals else 0
    mn = min(vals) if vals else 0
    if mn < 0:
        return 9 if mx < 2 ** 31 else 17
    if mx < 2 ** 16:
        return 3
    if mx < 2 ** 32:
        return 4
    return 16


def _write_ifd(fh, tags, bigtiff, endian):
    items = sorted(tags.items())
    entry_size = 20 if bigtiff else 12
    count = len(items)
    ptr_size = 8 if bigtiff else 4
    field_len = ptr_size  # inline value field size
    fh.write(struct.pack("<Q" if bigtiff else "<H", count))
    entry_pos = fh.tell()
    fh.write(b"\x00" * (count * entry_size + ptr_size))  # table + next ptr
    extra_pos = entry_pos + count * entry_size + ptr_size

    def stash(blob):
        """Write out-of-line data, return its file offset."""
        nonlocal extra_pos
        at = extra_pos
        fh.seek(at)
        fh.write(blob)
        extra_pos += len(blob)
        if len(blob) % 2:  # word-align
            fh.write(b"\x00")
            extra_pos += 1
        return at

    for i, (tag, value) in enumerate(items):
        ftype = _tiff_field_type(value)
        if ftype == 2:
            blob = value.encode("ascii") + b"\x00"
            cnt = len(blob)
        elif ftype == 12:
            vals = value if isinstance(value, (list, tuple)) else (value,)
            cnt = len(vals)
            blob = struct.pack("<%dd" % cnt, *vals)
        else:
            vals = value if isinstance(value, (list, tuple)) else (value,)
            cnt = len(vals)
            char = {3: "H", 4: "I", 9: "i", 16: "Q", 17: "q"}[ftype]
            blob = struct.pack("<%d%s" % (cnt, char), *vals)
        if len(blob) <= field_len:
            field = blob + b"\x00" * (field_len - len(blob))
        else:
            field = struct.pack("<Q" if bigtiff else "<I", stash(blob))
        entry = struct.pack("<HH", tag, ftype)
        entry += struct.pack("<Q" if bigtiff else "<I", cnt)
        entry += field
        fh.seek(entry_pos + i * entry_size)
        fh.write(entry)
    fh.seek(extra_pos)


def _encode_packbits(raw):
    out = bytearray()
    i, n = 0, len(raw)
    while i < n:
        # look for a run
        run = 1
        while i + run < n and raw[i + run] == raw[i] and run < 128:
            run += 1
        if run > 1:
            out.append(257 - run)
            out.append(raw[i])
            i += run
        else:
            j = i
            while j < n and (j - i) < 128:
                if j + 1 < n and raw[j] == raw[j + 1]:
                    break
                j += 1
            # j-i literal bytes (at least 1)
            lit = max(j - i, 1)
            out.append(lit - 1)
            out += raw[i:i + lit]
            i += lit
    return bytes(out)


def _encode_lzw(raw):
    """Simple TIFF LZW encoder (early-change) for tests/overviews."""
    CLEAR, EOI = 256, 257
    table = {bytes([i]): i for i in range(256)}
    next_code = 258
    width = 9
    out = bytearray()
    buf, bits = 0, 0

    def emit(code):
        nonlocal buf, bits
        buf = (buf << width) | code
        bits += width
        while bits >= 8:
            bits -= 8
            out.append((buf >> bits) & 0xFF)
            buf &= (1 << bits) - 1

    emit(CLEAR)
    w = b""
    for byte in raw:
        wc = w + bytes([byte])
        if wc in table:
            w = wc
        else:
            emit(table[w])
            if next_code < 4096:
                table[wc] = next_code
                next_code += 1
                # TIFF early-change, encoder side: widen when next_code
                # reaches 2**width. (The decoder widens one code sooner,
                # at 2**width - 1 -- the asymmetry is the spec's
                # "early change".)
                if next_code >= (1 << width) and width < 12:
                    width += 1
            else:
                emit(CLEAR)
                table = {bytes([i]): i for i in range(256)}
                next_code = 258
                width = 9
            w = bytes([byte])
    if w:
        emit(table[w])
    emit(EOI)
    if bits:
        out.append((buf << (8 - bits)) & 0xFF)
    return bytes(out)
