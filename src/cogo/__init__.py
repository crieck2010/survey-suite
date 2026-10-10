"""survey-cogo: coordinate geometry engine for surveying.

Pure-Python, dependency-free engine: inverses, forwards, intersections,
traverses (with Compass/Bowditch adjustment), and polygon area. No UI,
no I/O -- import it from any application or script.
"""

__version__ = "0.1.0"

from .angles import (
    azimuth_to_bearing,
    bearing_to_azimuth,
    decimal_to_dms,
    dms_to_decimal,
    format_dms,
    normalize_angle,
    parse_dms,
)
from .area import polygon_area, polygon_perimeter
from .forward import forward
from .intersections import bearing_bearing, distance_distance
from .inverse import Inverse, inverse
from .point import Point
from .traverse import (
    Leg,
    LinearMisclosure,
    angular_misclosure,
    azimuths_from_turned_angles,
    compass_adjust,
    linear_misclosure,
    relative_precision,
    run_traverse,
)

__all__ = [
    "__version__",
    "Point",
    "Leg",
    "Inverse",
    "LinearMisclosure",
    "dms_to_decimal",
    "parse_dms",
    "decimal_to_dms",
    "format_dms",
    "normalize_angle",
    "azimuth_to_bearing",
    "bearing_to_azimuth",
    "inverse",
    "forward",
    "bearing_bearing",
    "distance_distance",
    "azimuths_from_turned_angles",
    "run_traverse",
    "angular_misclosure",
    "linear_misclosure",
    "relative_precision",
    "compass_adjust",
    "polygon_area",
    "polygon_perimeter",
]
