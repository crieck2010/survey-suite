"""Build synthetic (Geo)TIFFs for the test suite using the engine's own
writer. Every file here exercises the reader; nothing depends on GDAL."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from basemap.tiff import (write_tiff, TAG_IMAGE_WIDTH, TAG_IMAGE_LENGTH,
                          TAG_BITS_PER_SAMPLE, TAG_COMPRESSION,
                          TAG_PHOTOMETRIC, TAG_SAMPLES_PER_PIXEL,
                          TAG_ROWS_PER_STRIP, TAG_PLANAR_CONFIG,
                          TAG_PREDICTOR, TAG_TILE_WIDTH, TAG_TILE_LENGTH,
                          TAG_SAMPLE_FORMAT, TAG_EXTRA_SAMPLES,
                          TAG_MODEL_PIXEL_SCALE, TAG_MODEL_TIEPOINT,
                          TAG_MODEL_TRANSFORMATION, TAG_GEO_KEY_DIRECTORY,
                          TAG_GEO_DOUBLE_PARAMS, TAG_GDAL_NODATA)


def _pattern_rgb(w, h, fn):
    px = bytearray()
    for y in range(h):
        for x in range(w):
            px += bytes(fn(x, y))
    return bytes(px)


def _pattern_gray(w, h, fn, bps=8):
    import struct
    if bps == 8:
        return bytes(fn(x, y) for y in range(h) for x in range(w))
    vals = [fn(x, y) for y in range(h) for x in range(w)]
    return struct.pack("<%dH" % len(vals), *vals)


def _georef_tags(origin=(500000.0, 4000000.0), gsd=0.05):
    ox, oy = origin
    return {
        TAG_MODEL_PIXEL_SCALE: (gsd, gsd, 0.0),
        TAG_MODEL_TIEPOINT: (0.0, 0.0, 0.0, ox, oy, 0.0),
    }


def _geokey_tags(epsg=32618):
    # minimal GeoKey directory: projected EPSG code
    return {
        TAG_GEO_KEY_DIRECTORY: (1, 1, 0, 3,
                                1024, 0, 1, 1,
                                1025, 0, 1, 1,
                                3072, 0, 1, epsg),
    }


def make_tif(path, w=64, h=48, kind="rgb", pattern=None,
             tiled=False, compression=1, predictor=1, planar=1, bps=8,
             photometric=None, georef=True, epsg=32618, nodata=None,
             transform=None, bigtiff=False, rows_per_strip=16,
             tile_size=32):
    """Write a synthetic GeoTIFF. ``kind``: rgb | gray | rgba.

    Returns (path, pixel_fn) where pixel_fn(x, y) gives the source sample
    tuple *before* photometric/predictor transforms.
    """
    spp = {"rgb": 3, "gray": 1, "rgba": 4}[kind]
    if pattern is None:
        def pattern(x, y):
            if kind == "gray":
                return (x * 4 + y * 2) % 256
            return ((x * 4) % 256, (y * 5) % 256, ((x + y) * 3) % 256)
    if kind == "gray":
        raw = _pattern_gray(w, h, pattern, bps)
    else:
        raw = _pattern_rgb(w, h, pattern)

    photo = photometric
    if photo is None:
        photo = 2 if spp >= 3 else 1
    if photo == 0 and kind == "gray":
        raw = bytes(255 - b for b in raw)

    tags = {
        TAG_IMAGE_WIDTH: w,
        TAG_IMAGE_LENGTH: h,
        TAG_BITS_PER_SAMPLE: tuple([bps] * spp),
        TAG_COMPRESSION: compression,
        TAG_PHOTOMETRIC: photo,
        TAG_SAMPLES_PER_PIXEL: spp,
        TAG_PLANAR_CONFIG: planar,
        TAG_SAMPLE_FORMAT: tuple([1] * spp),
    }
    if predictor != 1:
        tags[TAG_PREDICTOR] = predictor
    if kind == "rgba":
        tags[TAG_EXTRA_SAMPLES] = (2,)
    if georef:
        tags.update(_georef_tags())
        tags.update(_geokey_tags(epsg))
    if transform is not None:
        tags.pop(TAG_MODEL_PIXEL_SCALE, None)
        tags.pop(TAG_MODEL_TIEPOINT, None)
        tags[TAG_MODEL_TRANSFORMATION] = transform
    if nodata is not None:
        tags[TAG_GDAL_NODATA] = str(nodata)

    if tiled:
        tags[TAG_TILE_WIDTH] = min(tile_size, w)
        tags[TAG_TILE_LENGTH] = min(tile_size, h)
    else:
        tags[TAG_ROWS_PER_STRIP] = min(rows_per_strip, h)

    if planar == 2:
        # split into per-sample planes for the writer's block layout
        import struct
        if bps == 8:
            planes = [bytes(raw[i::spp]) for i in range(spp)]
        else:
            vals = struct.unpack("<%dH" % (w * h * spp), raw)
            planes = [struct.pack("<%dH" % (w * h),
                                  *[vals[i * spp + p]
                                    for i in range(w * h)])
                      for p in range(spp)]
        if predictor == 2:
            planes = [_difference_encode(pl, w, h, 1, bps)
                      for pl in planes]
        # planar-separate block order: plane index varies fastest
        blocks = []
        rps = min(rows_per_strip, h)
        if tiled:
            tw = min(tile_size, w)
            th = min(tile_size, h)
            grid = [(tx, ty, min(tw, w - tx), min(th, h - ty))
                    for ty in range(0, h, th) for tx in range(0, w, tw)]
        else:
            grid = [(0, y0, w, min(rps, h - y0))
                    for y0 in range(0, h, rps)]
        for tx, ty, bw, bh in grid:
            for pl in planes:
                tile = bytearray()
                for y in range(bh):
                    o = ((ty + y) * w + tx) * (bps // 8)
                    tile += pl[o:o + bw * (bps // 8)]
                    if tiled:
                        tile += b"\x00" * ((tw - bw) * (bps // 8))
                if tiled:
                    tile += b"\x00" * ((th - bh) * tw * (bps // 8))
                blocks.append((bytes(tile), compression))
    else:
        data = raw
        if predictor == 2:
            data = _difference_encode(data, w, h, spp, bps)
        blocks = _layout_blocks([data], w, h, spp, bps, tiled,
                                rows_per_strip, tile_size, compression)
    write_tiff(path, [(tags, blocks)], bigtiff=bigtiff)
    return path, pattern


def _difference_encode(data, w, h, spp, bps):
    """Forward horizontal differencing (what Predictor=2 undoes)."""
    import struct
    if bps == 8:
        a = bytearray(data)
        step = spp
        for y in range(h):
            base = y * w * step
            for x in range(w - 1, 0, -1):
                o = base + x * step
                p = o - step
                for s in range(spp):
                    a[o + s] = (a[o + s] - a[p + s]) & 0xFF
        return bytes(a)
    n = w * h * spp
    vals = list(struct.unpack("<%dH" % n, data[:n * 2]))
    for y in range(h):
        base = y * w * spp
        for x in range(w - 1, 0, -1):
            o = base + x * spp
            p = o - spp
            for s in range(spp):
                vals[o + s] = (vals[o + s] - vals[p + s]) & 0xFFFF
    return struct.pack("<%dH" % n, *vals)


def _layout_blocks(datas, w, h, spp, bps, tiled, rows_per_strip,
                   tile_size, compression):
    """Split sample data into strip/tile blocks. ``datas`` is [raw] for
    contiguous layout."""
    bpp = spp * (bps // 8)
    blocks = []
    if tiled:
        tw = min(tile_size, w)
        th = min(tile_size, h)
        for ty in range(0, h, th):
            for tx in range(0, w, tw):
                bw, bh = min(tw, w - tx), min(th, h - ty)
                tile = bytearray()
                for y in range(bh):
                    for x in range(bw):
                        for d in datas:
                            o = ((ty + y) * w + (tx + x)) * bpp
                            tile += d[o:o + bpp]
                    # pad short rows to the full tile width
                    tile += b"\x00" * ((tw - bw) * bpp)
                # pad short tiles to the full tile height
                tile += b"\x00" * ((th - bh) * tw * bpp)
                blocks.append((bytes(tile), compression))
    else:
        rps = min(rows_per_strip, h)
        for y0 in range(0, h, rps):
            bh = min(rps, h - y0)
            strip = bytearray()
            for d in datas:
                strip += d[y0 * w * bpp:(y0 + bh) * w * bpp]
            blocks.append((bytes(strip), compression))
    return blocks
