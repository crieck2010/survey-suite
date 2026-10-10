"""survey-basemap: drone basemap layer engine for the land-surveying suite."""

from .errors import (BasemapError, CorruptTiff, UnsupportedTiff,
                     NoGeoreferencing, CRSMismatch, OverviewError)
from .raster import GeoTIFFRaster
from .overview import build_overviews, overview_info
from .quality import quality_report, check_scale
from .drafting_adapter import GeoTIFFRasterSource

__version__ = "0.1.0"

__all__ = [
    "BasemapError", "CorruptTiff", "UnsupportedTiff", "NoGeoreferencing",
    "CRSMismatch", "OverviewError",
    "GeoTIFFRaster", "GeoTIFFRasterSource",
    "build_overviews", "overview_info",
    "quality_report", "check_scale",
    "__version__",
]
