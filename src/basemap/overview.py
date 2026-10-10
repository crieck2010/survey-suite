"""Overview pyramids: downsampled sidecar levels for fast rendering.

``build_overviews`` writes ``<path>.ovr`` -- a standard multi-IFD TIFF
whose levels any GDAL-based tool can also read (QGIS will pick them up
automatically). Each level halves the dimensions until the long side drops
below ``min_size`` px.

The levels are generated with the engine's own box resampler, so this is
pure Python and therefore slow on huge orthomosaics -- roughly tens of
megapixels per minute. That is a one-time cost per orthomosaic, documented
honestly in docs/INTEROP.md; the payoff is that every later render,
thumbnail, and plat export reads only the level it needs.

If you already have GDAL, ``gdaladdo`` produces equivalent (faster)
``.ovr`` files this engine reads the same way.
"""

import os

from .errors import OverviewError
from .raster import GeoTIFFRaster, _box_resample
from .tiff import (write_tiff, TAG_IMAGE_WIDTH, TAG_IMAGE_LENGTH,
                   TAG_BITS_PER_SAMPLE, TAG_COMPRESSION, TAG_PHOTOMETRIC,
                   TAG_SAMPLES_PER_PIXEL, TAG_TILE_WIDTH, TAG_TILE_LENGTH,
                   TAG_MODEL_PIXEL_SCALE, TAG_MODEL_TIEPOINT)


def overview_levels_for(width, height, min_size=256, factor=2):
    """Planned (w, h) for each overview level (level 1 = first)."""
    levels = []
    w, h = width, height
    while max(w, h) // factor >= min_size:
        w = (w + factor - 1) // factor
        h = (h + factor - 1) // factor
        levels.append((w, h))
    return levels


def build_overviews(path, min_size=256, factor=2, tile=512,
                    compression=8):
    """Generate ``<path>.ovr`` with downsampled levels.

    Returns the sidecar path. ``compression`` is a TIFF compression code
    (8 = deflate default). Levels carry scaled ModelPixelScale/ModelTiepoint
    tags so they stay georeferenced.
    """
    raster = GeoTIFFRaster(path)
    try:
        planned = overview_levels_for(raster.width, raster.height,
                                      min_size, factor)
        if not planned:
            raise OverviewError(
                f"{path}: image {raster.width}x{raster.height} is smaller "
                f"than min_size {min_size} -- no overviews needed")
        sx, sy = raster.transform.a, -raster.transform.e
        ox, oy = raster.transform.c, raster.transform.f
        ifds = []
        prev_w, prev_h = raster.width, raster.height
        prev_rgb, _, _ = raster.read_window(0, 0, prev_w, prev_h)
        for w, h in planned:
            rgb, _, _ = _box_resample(prev_rgb, prev_w, prev_h, w, h)
            k = raster.width / w
            tags = {
                TAG_IMAGE_WIDTH: w,
                TAG_IMAGE_LENGTH: h,
                TAG_BITS_PER_SAMPLE: (8, 8, 8),
                TAG_COMPRESSION: compression,
                TAG_PHOTOMETRIC: 2,
                TAG_SAMPLES_PER_PIXEL: 3,
                TAG_TILE_WIDTH: min(tile, w),
                TAG_TILE_LENGTH: min(tile, h),
                TAG_MODEL_PIXEL_SCALE: (sx * k, sy * k, 0.0),
                TAG_MODEL_TIEPOINT: (0.0, 0.0, 0.0, ox, oy, 0.0),
            }
            blocks = _split_tiles(rgb, w, h, min(tile, w), min(tile, h),
                                  compression)
            ifds.append((tags, blocks))
            prev_rgb, prev_w, prev_h = rgb, w, h
        ovr_path = path + ".ovr"
        write_tiff(ovr_path, ifds)
        return ovr_path
    finally:
        raster.close()


def _split_tiles(rgb, w, h, tw, th, compression):
    blocks = []
    for ty in range(0, h, th):
        for tx in range(0, w, tw):
            bw, bh = min(tw, w - tx), min(th, h - ty)
            tile = bytearray(3 * bw * bh)
            for y in range(bh):
                src = ((ty + y) * w + tx) * 3
                dst = y * bw * 3
                tile[dst:dst + bw * 3] = rgb[src:src + bw * 3]
            blocks.append((bytes(tile), compression))
    return blocks


def overview_info(path):
    """Describe existing overview levels (sidecar or internal)."""
    raster = GeoTIFFRaster(path)
    try:
        return [{"width": lv.width, "height": lv.height,
                 "internal": not hasattr(lv, "_tif_ref")}
                for lv in raster.overview_ifds]
    finally:
        raster.close()
