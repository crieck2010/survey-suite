"""GeoTIFFRaster: decode, windowed reads, nodata, and statistics.

The decode pipeline for one block (strip or tile):

    raw bytes -> decompress -> undo predictor -> interleave planes (if
    separate) -> per-sample 8-bit conversion -> photometric fixup ->
    RGBA/nodata compositing over white

``read_window`` decodes only the blocks intersecting the requested pixel
window, so a viewport render over a multi-GB orthomosaic never touches
most of the file. ``render`` downsamples a window to a target output size
with a box filter -- this is what the drafting adapter serves to the PDF
composer.
"""

import struct

from .errors import CorruptTiff, UnsupportedTiff
from .tiff import (TiffFile, decompress, undo_predictor, COMPRESSION_NAMES,
                   TAG_GDAL_NODATA)


def _check_supported(ifd, path):
    comp = ifd.compression
    if comp in (6, 7):
        raise UnsupportedTiff(
            f"{path}: JPEG-in-TIFF compression is not supported in v1 -- "
            f"re-export with Deflate or LZW")
    if comp not in (1, 5, 8, 32773, 32946):
        name = COMPRESSION_NAMES.get(comp, str(comp))
        raise UnsupportedTiff(
            f"{path}: compression {name} ({comp}) is not supported in v1")
    bps = ifd.bits_per_sample
    if any(b not in (8, 16) for b in bps):
        raise UnsupportedTiff(
            f"{path}: BitsPerSample {bps} not supported in v1 "
            f"(8/16-bit unsigned only)")
    if any(f not in (1,) for f in ifd.sample_format):
        raise UnsupportedTiff(
            f"{path}: non-unsigned-integer samples are not supported in v1")
    if ifd.photometric not in (0, 1, 2):
        raise UnsupportedTiff(
            f"{path}: PhotometricInterpretation {ifd.photometric} not "
            f"supported in v1 (0/1/2 only)")
    spp = ifd.samples_per_pixel
    if spp not in (1, 3, 4):
        raise UnsupportedTiff(
            f"{path}: {spp} samples/pixel not supported in v1")
    if ifd.planar not in (1, 2):
        raise UnsupportedTiff(
            f"{path}: PlanarConfiguration {ifd.planar} not supported")


def _decode_block(tif, ifd, index, path):
    """Decode one strip/tile to a flat sample buffer in contiguous
    (pixel-interleaved) order. Returns (bytes, block_w, block_h).

    For PlanarConfiguration 2 (separate), ``index`` is the strip/tile
    index; the spp per-plane blocks live at ``index * spp + p`` (plane
    index varies fastest, per the TIFF spec).
    """
    w, h = ifd.width, ifd.height
    spp = ifd.samples_per_pixel
    bps = ifd.bits_per_sample[0]
    if any(b != bps for b in ifd.bits_per_sample):
        raise UnsupportedTiff(
            f"{path}: mixed BitsPerSample {ifd.bits_per_sample} "
            f"not supported in v1")

    if ifd.is_tiled:
        tw, th = ifd.scalar(322), ifd.scalar(323)
        tiles_across = (w + tw - 1) // tw
        tx, ty = index % tiles_across, index // tiles_across
        bw, bh = min(tw, w - tx * tw), min(th, h - ty * th)
        full_tw, full_th = tw, th
    else:
        rps = ifd.scalar(278, 2 ** 32 - 1)
        rps = min(rps, h)
        bw, bh = w, min(rps, h - index * rps)
        full_tw, full_th = w, rps

    if ifd.predictor not in (1, 2):
        raise UnsupportedTiff(
            f"{path}: Predictor {ifd.predictor} not supported in v1")

    # On-disk block dimensions: edge tiles are padded to the full tile
    # size (TIFF spec); strips are never padded.
    if ifd.is_tiled:
        data_tw, data_th = full_tw, full_th
    else:
        data_tw, data_th = w, bh

    def decode_one(block_index, plane_spp):
        raw = tif.read_block(ifd, block_index)
        data = decompress(raw, ifd.compression, path)
        expect = data_tw * data_th * plane_spp * (bps // 8)
        if len(data) < expect:
            raise CorruptTiff(
                f"{path}: block {block_index} decoded to {len(data)} "
                f"bytes, expected {expect}")
        return data[:expect]

    if ifd.planar == 2:
        # separate planes: decode/predictor-crop per plane, then interleave
        planes = []
        for p in range(spp):
            data = decode_one(index * spp + p, 1)
            if ifd.predictor == 2:
                data = undo_predictor(data, data_tw, data_th, 1, bps)
            if bw != data_tw or bh != data_th:
                data = _crop_block(data, data_tw, data_th, bw, bh, 1, bps)
            planes.append(data)
        data = _interleave_planes(planes, bw, bh, bps)
    else:
        data = decode_one(index, spp)
        if ifd.predictor == 2:
            data = undo_predictor(data, data_tw, data_th, spp, bps)
        if bw != data_tw or bh != data_th:
            data = _crop_block(data, data_tw, data_th, bw, bh, spp, bps)
    return data, bw, bh


def _interleave_planes(planes, w, h, bps):
    spp = len(planes)
    if bps == 8:
        out = bytearray(w * h * spp)
        for i in range(w * h):
            for p in range(spp):
                out[i * spp + p] = planes[p][i]
        return bytes(out)
    vals = []
    for p in range(spp):
        vals.append(list(struct.unpack("<%dH" % (w * h),
                                       planes[p][:w * h * 2])))
    inter = [0] * (w * h * spp)
    for i in range(w * h):
        for p in range(spp):
            inter[i * spp + p] = vals[p][i]
    return struct.pack("<%dH" % len(inter), *inter)


def _crop_block(data, full_w, full_h, w, h, spp, bps):
    bpp = spp * (bps // 8)
    row = full_w * bpp
    return b"".join(data[y * row:y * row + w * bpp] for y in range(h))


def _to_8bit(data, bps):
    if bps == 8:
        return data
    n = len(data) // 2
    vals = struct.unpack("<%dH" % n, data[:n * 2])
    return bytes((v * 255 + 32768) // 65535 for v in vals)


def _assemble_rgb(data8, w, h, spp, photometric, nodata_mask=None):
    """Assemble 8-bit samples into RGB bytes. Returns (rgb_bytes, w, h)."""
    n = w * h
    if spp == 1:
        gray = bytearray(data8[:n])
        if photometric == 0:  # WhiteIsZero -> invert
            for i in range(n):
                gray[i] = 255 - gray[i]
        rgb = bytearray(3 * n)
        rgb[0::3] = gray
        rgb[1::3] = gray
        rgb[2::3] = gray
    else:
        rgb = bytearray(data8[:3 * n])
        if photometric == 0:
            for i in range(3 * n):
                rgb[i] = 255 - rgb[i]
        if spp == 4:
            alpha = data8[3::4][:n] if len(data8) >= 4 * n else None
            if alpha is None:  # separate-planar 4th plane edge case
                alpha = bytes([255]) * n
            for i in range(n):
                a = alpha[i] / 255.0
                o = 3 * i
                rgb[o] = int(rgb[o] * a + 255 * (1 - a))
                rgb[o + 1] = int(rgb[o + 1] * a + 255 * (1 - a))
                rgb[o + 2] = int(rgb[o + 2] * a + 255 * (1 - a))
    if nodata_mask is not None:
        for i in range(n):
            if nodata_mask[i]:
                o = 3 * i
                rgb[o] = rgb[o + 1] = rgb[o + 2] = 255
    return bytes(rgb), w, h


class GeoTIFFRaster:
    """A GeoTIFF orthomosaic with windowed, pyramid-aware reads.

    The file handle stays open; use as a context manager or call close().
    """

    def __init__(self, path):
        from .geo import geotransform_from_ifd  # lazy: clearer tracebacks
        from .crs import crs_from_ifd
        self.path = path
        self._tif = TiffFile(path)
        self._ifd = self._tif.main_ifd
        _check_supported(self._ifd, path)
        self.width = self._ifd.width
        self.height = self._ifd.height
        if not self.width or not self.height:
            raise CorruptTiff(f"{path}: zero image dimensions")
        self.transform = geotransform_from_ifd(self._ifd, path)
        try:
            self.crs = crs_from_ifd(self._ifd, path)
        except Exception:
            self.crs = None
        self._nodata = None
        if TAG_GDAL_NODATA in self._ifd.tags:
            raw_nd = self._ifd.values(TAG_GDAL_NODATA)
            raw_nd = raw_nd[0] if raw_nd else None
            if raw_nd is not None:
                try:
                    self._nodata = float(raw_nd)
                except (TypeError, ValueError):
                    raise CorruptTiff(
                        f"{path}: GDAL_NODATA tag is not numeric: "
                        f"{raw_nd!r}")
        self._overviews = None  # lazy

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self._tif.close()

    # -- layout ---------------------------------------------------------------
    def _block_grid(self, ifd):
        w, h = ifd.width, ifd.height
        if ifd.is_tiled:
            tw, th = ifd.scalar(322), ifd.scalar(323)
            return ("tile", tw, th,
                    (w + tw - 1) // tw, (h + th - 1) // th)
        rps = min(ifd.scalar(278, 2 ** 32 - 1), h)
        return ("strip", w, rps, 1, (h + rps - 1) // rps)

    def _tif_for(self, ifd):
        # overview IFDs from a .ovr sidecar live on another TiffFile
        return getattr(ifd, "_tif_ref", self._tif)

    # -- reads ------------------------------------------------------------------
    def read_window(self, x0, y0, x1, y1, ifd=None):
        """Decode the pixel window [x0,x1) x [y0,y1) to 8-bit RGB.

        Only blocks intersecting the window are decoded. Returns
        (rgb_bytes, w, h).
        """
        ifd = ifd or self._ifd
        tif = self._tif_for(ifd)
        iw, ih = ifd.width, ifd.height
        x0 = max(0, int(x0))
        y0 = max(0, int(y0))
        x1 = min(iw, int(x1))
        y1 = min(ih, int(y1))
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"empty window [{x0},{x1}) x [{y0},{y1})")
        kind, bw, bh, across, down = self._block_grid(ifd)
        w, h = x1 - x0, y1 - y0
        spp = ifd.samples_per_pixel
        out = bytearray(3 * w * h)
        for by in range(y0 // bh, (y1 - 1) // bh + 1):
            for bx in range(x0 // bw, (x1 - 1) // bw + 1):
                idx = by * across + bx
                data, dbw, dbh = _decode_block(tif, ifd, idx, self.path)
                data8 = _to_8bit(data, ifd.bits_per_sample[0])
                # block origin in pixels
                ox, oy = bx * bw, by * bh
                # intersect with window
                ix0, iy0 = max(x0, ox), max(y0, oy)
                ix1, iy1 = min(x1, ox + dbw), min(y1, oy + dbh)
                sub = _assemble_sub(data8, dbw, dbh, ix0 - ox, iy0 - oy,
                                    ix1 - ix0, iy1 - iy0, ifd, self._nodata)
                for ry in range(iy1 - iy0):
                    dst = ((iy0 - y0 + ry) * w + (ix0 - x0)) * 3
                    src = ry * (ix1 - ix0) * 3
                    out[dst:dst + (ix1 - ix0) * 3] = \
                        sub[src:src + (ix1 - ix0) * 3]
        return bytes(out), w, h

    def render(self, max_px=4096, ifd=None):
        """Full-extent render capped at ``max_px`` on the long side.

        Uses an overview level when one is close to the target size, so a
        multi-GB orthomosaic renders in seconds, not minutes. Returns
        (rgb_bytes, w, h).
        """
        ifd = ifd or self._ifd
        scale = max_px / max(ifd.width, ifd.height)
        if scale >= 1.0:
            return self.read_window(0, 0, ifd.width, ifd.height, ifd=ifd)
        # pick the smallest overview that still covers the target size,
        # else decode the main image directly
        target_w = max(1, int(ifd.width * scale))
        best = ifd
        for ov in self.overview_ifds:
            if ov.width >= target_w and ov.width < best.width:
                best = ov
        out_w = max(1, int(round(ifd.width * max_px
                                 / max(ifd.width, ifd.height))))
        out_h = max(1, int(round(ifd.height * max_px
                                 / max(ifd.width, ifd.height))))
        rgb, _, _ = self.read_window(0, 0, best.width, best.height,
                                     ifd=best)
        return _box_resample(rgb, best.width, best.height, out_w, out_h)

    @property
    def overview_ifds(self):
        """Overview levels: sidecar .ovr first, then internal overviews."""
        if self._overviews is None:
            self._overviews = _sidecar_overviews(self.path) or \
                self._tif.overview_ifds
        return self._overviews

    # -- metadata -----------------------------------------------------------------
    def extent(self):
        return self.transform.extent(self.width, self.height)

    @property
    def gsd(self):
        return (self.transform.gsd_x, self.transform.gsd_y)

    def info(self):
        ifd = self._ifd
        comp = COMPRESSION_NAMES.get(ifd.compression, ifd.compression)
        xmin, ymin, xmax, ymax = self.extent()
        return {
            "path": self.path,
            "width": self.width,
            "height": self.height,
            "bands": ifd.samples_per_pixel,
            "bits_per_sample": list(ifd.bits_per_sample),
            "compression": comp,
            "tiled": ifd.is_tiled,
            "photometric": ifd.photometric,
            "crs": str(self.crs) if self.crs else "unknown",
            "gsd_x_m": self.transform.gsd_x,
            "gsd_y_m": self.transform.gsd_y,
            "extent": {"xmin": xmin, "ymin": ymin,
                       "xmax": xmax, "ymax": ymax},
            "nodata": self._nodata,
            "overview_levels": len(self.overview_ifds),
            "bigtiff": self._tif._big,
        }

    def band_stats(self, sample_stride=16):
        """Per-band min/max/mean over a strided sample (documented
        approximation for huge rasters; exact for small ones)."""
        ifd = self._ifd
        spp = ifd.samples_per_pixel
        bps = ifd.bits_per_sample[0]
        maxv = (1 << bps) - 1
        lo = [maxv] * spp
        hi = [0] * spp
        tot = [0] * spp
        cnt = [0] * spp
        kind, bw, bh, across, down = self._block_grid(ifd)
        for idx in range(0, across * down, sample_stride):
            data, dbw, dbh = _decode_block(self._tif, ifd, idx, self.path)
            if bps == 8:
                vals = data
            else:
                n = len(data) // 2
                vals = struct.unpack("<%dH" % n, data[:n * 2])
            step = spp
            for i in range(0, dbw * dbh):
                for s in range(spp):
                    v = vals[i * step + s]
                    if v < lo[s]:
                        lo[s] = v
                    if v > hi[s]:
                        hi[s] = v
                    tot[s] += v
                    cnt[s] += 1
        return [{"min": lo[s], "max": hi[s],
                 "mean": (tot[s] / cnt[s] if cnt[s] else 0)}
                for s in range(spp)]

    def nodata_fraction(self, sample_stride=16):
        """Fraction of sampled pixels equal to the nodata value (0.0 when
        the file carries no nodata tag)."""
        if self._nodata is None:
            return 0.0
        ifd = self._ifd
        spp = ifd.samples_per_pixel
        bps = ifd.bits_per_sample[0]
        nd = self._nodata
        kind, bw, bh, across, down = self._block_grid(ifd)
        hit = tot = 0
        for idx in range(0, across * down, sample_stride):
            data, dbw, dbh = _decode_block(self._tif, ifd, idx, self.path)
            if bps == 8:
                vals = data
            else:
                n = len(data) // 2
                vals = struct.unpack("<%dH" % n, data[:n * 2])
            for i in range(0, dbw * dbh):
                tot += 1
                px = vals[i * spp:(i + 1) * spp]
                check = px[:3] if spp > 1 else px[:1]
                if all(x == nd for x in check):
                    hit += 1
        return hit / tot if tot else 0.0


def _assemble_sub(data8, bw, bh, sx, sy, w, h, ifd, nodata):
    """Crop a decoded block to a sub-rectangle and assemble RGB."""
    spp = ifd.samples_per_pixel
    bpp = spp  # data8 is 8-bit per sample now
    rows = []
    for y in range(sy, sy + h):
        rows.append(data8[y * bw * bpp + sx * bpp:
                          y * bw * bpp + (sx + w) * bpp])
    sub = b"".join(rows)
    mask = None
    if nodata is not None:
        nd = int(nodata) & 0xFF
        mask = bytearray(w * h)
        for i in range(w * h):
            px = sub[i * spp:(i + 1) * spp]
            check = px[:3] if spp > 1 else px[:1]
            if all(b == nd for b in check):
                mask[i] = 1
    return _assemble_rgb(sub, w, h, spp, ifd.photometric,
                         nodata_mask=mask)[0]


def _box_resample(rgb, w, h, out_w, out_h):
    """Box-filter downsample of RGB bytes. Returns (bytes, out_w, out_h)."""
    out = bytearray(3 * out_w * out_h)
    for oy in range(out_h):
        y0 = oy * h // out_h
        y1 = max(y0 + 1, (oy + 1) * h // out_h)
        for ox in range(out_w):
            x0 = ox * w // out_w
            x1 = max(x0 + 1, (ox + 1) * w // out_w)
            r = g = b = n = 0
            for y in range(y0, y1):
                base = y * w * 3
                for x in range(x0, x1):
                    o = base + x * 3
                    r += rgb[o]
                    g += rgb[o + 1]
                    b += rgb[o + 2]
                    n += 1
            o = (oy * out_w + ox) * 3
            out[o] = r // n
            out[o + 1] = g // n
            out[o + 2] = b // n
    return bytes(out), out_w, out_h


def _sidecar_overviews(path):
    """Read overview levels from a ``<path>.ovr`` sidecar if present."""
    import os
    ovr_path = path + ".ovr"
    if not os.path.exists(ovr_path):
        return None
    try:
        tif = TiffFile(ovr_path)
    except Exception:
        return None
    # keep the handle referenced; levels share it
    levels = sorted(tif.ifds, key=lambda i: i.pixel_count(),
                    reverse=True)
    # stash the TiffFile on the first IFD so it isn't GC'd/closed
    for lv in levels:
        lv._tif_ref = tif
    return levels
