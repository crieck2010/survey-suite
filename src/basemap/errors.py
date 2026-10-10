"""Exception hierarchy for survey-basemap.

Every failure names the file, the tag/offset involved where relevant, and
the reason. Corrupt or unsupported inputs always fail loud -- a basemap must
never silently misrender under survey linework.
"""


class BasemapError(Exception):
    """Base class for all survey-basemap errors."""


class CorruptTiff(BasemapError):
    """The file claims to be TIFF/GeoTIFF but is truncated or malformed."""


class UnsupportedTiff(BasemapError):
    """A valid TIFF using features this engine deliberately does not
    support in v1 (JPEG compression, float samples, CMYK, ...)."""


class NoGeoreferencing(BasemapError):
    """The TIFF has no usable georeferencing tags."""


class CRSMismatch(BasemapError):
    """The basemap CRS does not match the project CRS. v1 fails loud
    rather than reprojecting silently (see docs/INTEROP.md)."""


class OverviewError(BasemapError):
    """Pyramid/overview generation or reading failed."""
