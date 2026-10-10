"""GeoTIFF georeferencing: pixel <-> world transforms from the standard tags.

Three tag sets are understood, in priority order:

1. ``ModelTransformationTag`` (34264) -- a full 4x4 matrix mapping pixel
   (col, row, 0) to world (x, y, z). Handles rotation/shear; GSD is derived
   from the column/row vector lengths.
2. ``ModelPixelScaleTag`` (33550) + ``ModelTiepointTag`` (33922) -- the
   common north-up case: ``world = origin + pixel * scale``.
3. Nothing -- :class:`NoGeoreferencing` is raised; a basemap without a
   known placement must never render silently under survey linework.

``GeoKeyDirectoryTag`` (34735) + ``GeoDoubleParamsTag`` (34736) +
``GeoAsciiParamsTag`` (34737) are parsed into a plain dict of GeoKey id ->
value; CRS interpretation lives in :mod:`basemap.crs`.
"""

from .errors import NoGeoreferencing
from .tiff import (TAG_MODEL_PIXEL_SCALE, TAG_MODEL_TIEPOINT,
                   TAG_MODEL_TRANSFORMATION, TAG_GEO_KEY_DIRECTORY,
                   TAG_GEO_DOUBLE_PARAMS, TAG_GEO_ASCII_PARAMS)

# GeoKey ids we interpret
GT_MODEL_TYPE = 1024
GT_RASTER_TYPE = 1025
GEOGRAPHIC_TYPE = 2048
PROJECTED_CRS_TYPE = 3072
PROJ_COORD_TRANS = 3076

_MODEL_TYPE_NAMES = {0: "undefined", 1: "projected", 2: "geographic",
                      3: "geocentric"}


class GeoTransform:
    """Affine pixel -> world mapping.

    ``world_x = a * col + b * row + c``,
    ``world_y = d * col + e * row + f``.
    """

    def __init__(self, a, b, c, d, e, f):
        self.a, self.b, self.c = a, b, c
        self.d, self.e, self.f = d, e, f

    def pixel_to_world(self, col, row):
        return (self.a * col + self.b * row + self.c,
                self.d * col + self.e * row + self.f)

    def world_to_pixel(self, x, y):
        det = self.a * self.e - self.b * self.d
        if det == 0:
            raise NoGeoreferencing("degenerate geotransform (det=0)")
        col = (self.e * (x - self.c) - self.b * (y - self.f)) / det
        row = (-self.d * (x - self.c) + self.a * (y - self.f)) / det
        return (col, row)

    @property
    def gsd_x(self):
        """Ground sample distance along image columns (metres)."""
        return (self.a ** 2 + self.d ** 2) ** 0.5

    @property
    def gsd_y(self):
        """Ground sample distance along image rows (metres)."""
        return (self.b ** 2 + self.e ** 2) ** 0.5

    @property
    def is_north_up(self):
        return self.b == 0.0 and self.d == 0.0 and self.e < 0 < self.a

    def extent(self, width, height):
        xs, ys = [], []
        for col, row in ((0, 0), (width, 0), (0, height), (width, height)):
            x, y = self.pixel_to_world(col, row)
            xs.append(x)
            ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys))

    def __repr__(self):
        return (f"GeoTransform(a={self.a!r}, b={self.b!r}, c={self.c!r}, "
                f"d={self.d!r}, e={self.e!r}, f={self.f!r})")


def geotransform_from_ifd(ifd, path="<memory>"):
    """Build the pixel->world transform for an IFD. Raises
    :class:`NoGeoreferencing` when no usable tags exist."""
    trans = ifd.values(TAG_MODEL_TRANSFORMATION)
    if trans is not None:
        if len(trans) < 16:
            raise NoGeoreferencing(
                f"{path}: ModelTransformationTag has {len(trans)} values, "
                f"need 16")
        # matrix rows map (col, row, z, 1) -> (x, y, z, w)
        m = trans
        return GeoTransform(m[0], m[1], m[3], m[4], m[5], m[7])
    scale = ifd.values(TAG_MODEL_PIXEL_SCALE)
    tie = ifd.values(TAG_MODEL_TIEPOINT)
    if scale is not None and tie is not None:
        if len(scale) < 3:
            raise NoGeoreferencing(
                f"{path}: ModelPixelScaleTag needs 3 values")
        if len(tie) < 6:
            raise NoGeoreferencing(
                f"{path}: ModelTiepointTag needs 6 values per tiepoint")
        sx, sy = scale[0], scale[1]
        # first tiepoint: (i, j, k, x, y, z); pixel (i,j) sits at world (x,y)
        i, j, _k, x, y, _z = tie[0:6]
        # world = (x + (col - i) * sx, y - (row - j) * sy) for north-up rasters
        return GeoTransform(sx, 0.0, x - i * sx,
                            0.0, -sy, y + j * sy)
    raise NoGeoreferencing(
        f"{path}: no ModelTransformationTag and no "
        f"ModelPixelScale/ModelTiepoint pair -- cannot place this raster")


def parse_geokeys(ifd):
    """Parse the GeoKey directory into {key_id: value}.

    SHORT values stored inline come back as ints; DOUBLE values as floats;
    ASCII values as strings (pipe- and null-trimmed).
    """
    directory = ifd.values(TAG_GEO_KEY_DIRECTORY)
    if directory is None:
        return {}
    directory = list(directory)
    if len(directory) < 4:
        return {}
    n_keys = int(directory[3])
    doubles = list(ifd.values(TAG_GEO_DOUBLE_PARAMS, ()))
    ascii_blob = ifd.values(TAG_GEO_ASCII_PARAMS)
    ascii_text = ascii_blob[0] if ascii_blob else ""
    keys = {}
    for k in range(n_keys):
        base = 4 + 4 * k
        if base + 4 > len(directory):
            break
        key_id, loc, count, offset = (int(directory[base + i])
                                      for i in range(4))
        if loc == 0:
            keys[key_id] = offset
        elif loc == 34736:
            vals = doubles[offset:offset + count]
            keys[key_id] = vals[0] if count == 1 else tuple(vals)
        elif loc == 34737:
            keys[key_id] = ascii_text[offset:offset + count].rstrip("| \x00")
        # other locations: ignore (not needed for CRS reporting)
    return keys


def geokey_summary(keys):
    """One-line human summary of the GeoKeys, e.g.
    ``"projected EPSG:32618"``."""
    model = _MODEL_TYPE_NAMES.get(keys.get(GT_MODEL_TYPE, 0), "unknown")
    epsg = keys.get(PROJECTED_CRS_TYPE) or keys.get(GEOGRAPHIC_TYPE)
    if epsg:
        return f"{model} EPSG:{int(epsg)}"
    return f"{model} (no EPSG code in GeoKeys)"
