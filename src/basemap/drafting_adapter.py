"""Adapter: GeoTIFF basemaps as survey-drafting ``RasterSource`` objects.

This module is the build #4 -> build #3 joint. ``survey-drafting`` is an
*optional* dependency: it is imported lazily, and when it is not installed
a local protocol shim with the identical method names is used instead, so
this package stays dependency-free and importable on its own.

The desktop app (build #5) wires the two together::

    from basemap.drafting_adapter import GeoTIFFRasterSource
    from drafting.layers import build_layers

    src = GeoTIFFRasterSource("ortho.tif", project_crs="EPSG:26918",
                              opacity=0.85)
    layers = build_layers(parcel, points, style, basemap=src)
    layers["basemap"].visible = False   # print-time toggle, as before

No composer changes are needed in survey-drafting: the composer draws any
``RasterSource`` on the ``basemap`` layer, stretched over
``extent_world()``.

Design notes, stated honestly:

- ``image()`` serves the *full extent* at a capped render resolution
  (``max_render_px`` on the long side, default 4096), sourced from the
  overview pyramid when one exists. The composer stretches it over the
  full world extent, so geometry stays exact while a multi-GB orthomosaic
  never gets fully decoded for one plat.
- ``opacity`` is pre-composited as a fade toward white at decode time.
  survey-drafting v1 has no alpha-channel support in its PDF writer, so a
  true alpha blend would need composer changes -- the fade is the honest
  v1 behaviour and is documented as such.
- CRS is checked against ``project_crs`` at construction and fails loud
  on mismatch (see :mod:`basemap.crs`). Pass ``project_crs=None`` to skip
  the check (not recommended).
"""

try:
    from drafting.layers import RasterSource as _RasterSourceBase
    _DRAFTING_AVAILABLE = True
except Exception:  # ImportError or anything else at import time
    _DRAFTING_AVAILABLE = False

    class _RasterSourceBase:  # noqa: D101 -- protocol shim
        name = "raster"

        def extent_world(self):
            raise NotImplementedError

        def image(self):
            raise NotImplementedError


class GeoTIFFRasterSource(_RasterSourceBase):
    """A GeoTIFF orthomosaic implementing the drafting RasterSource
    protocol (``extent_world`` + ``image``)."""

    name = "geotiff-basemap"

    def __init__(self, path, project_crs=None, max_render_px=4096,
                 opacity=1.0):
        from .raster import GeoTIFFRaster
        from .crs import ensure_crs_match
        if not 0.0 < opacity <= 1.0:
            raise ValueError(f"opacity must be in (0, 1], got {opacity}")
        self.path = path
        self.max_render_px = int(max_render_px)
        self.opacity = float(opacity)
        self.visible = True  # print-time toggle, honored by the composer
        self._raster = GeoTIFFRaster(path)
        if self._raster.crs is None:
            from .errors import NoGeoreferencing
            raise NoGeoreferencing(
                f"{path}: no CRS in GeoKeys -- cannot use as a survey "
                f"basemap")
        if project_crs is not None:
            ensure_crs_match(self._raster.crs, project_crs, path)
        self.crs = self._raster.crs

    def close(self):
        self._raster.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- RasterSource protocol --------------------------------------------------
    def extent_world(self):
        return self._raster.extent()

    def image(self):
        """(bytes, w, h, kind): full-extent RGB at the capped render
        resolution, opacity pre-composited as a fade toward white."""
        rgb, w, h = self._raster.render(max_px=self.max_render_px)
        if self.opacity < 1.0:
            fade = 1.0 - self.opacity
            data = bytes(int(v * self.opacity + 255 * fade) for v in rgb)
        else:
            data = rgb
        return data, w, h, "rgb"

    # -- introspection for the app ------------------------------------------------
    def info(self):
        d = self._raster.info()
        d["opacity"] = self.opacity
        d["max_render_px"] = self.max_render_px
        d["drafting_available"] = _DRAFTING_AVAILABLE
        return d


def is_drafting_available():
    """True when survey-drafting is importable (build #5 environment)."""
    return _DRAFTING_AVAILABLE
