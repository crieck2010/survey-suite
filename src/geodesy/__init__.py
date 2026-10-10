"""survey-geodesy: geodetic computation engine for surveying.

Pure-Python, dependency-free engine: reference ellipsoids, geodetic/ECEF
conversions, Helmert datum transformations, Transverse Mercator and UTM
projections, and Vincenty geodesic distances. No UI, no I/O -- import it
from any application or script.
"""

__version__ = "0.1.0"

from .conversions import ecef_to_geodetic, geodetic_to_ecef
from .ellipsoids import AIRY1830, CLARKE1866, GRS80, WGS84, ELLIPSOIDS, Ellipsoid
from .helmert import HelmertParams, helmert_3param, helmert_7param
from .transverse_mercator import tm_forward, tm_inverse
from .utm import latlon_to_utm, utm_to_latlon, utm_zone
from .vincenty import geodesic_inverse

__all__ = [
    "__version__",
    "Ellipsoid",
    "ELLIPSOIDS",
    "WGS84",
    "GRS80",
    "CLARKE1866",
    "AIRY1830",
    "geodetic_to_ecef",
    "ecef_to_geodetic",
    "HelmertParams",
    "helmert_7param",
    "helmert_3param",
    "tm_forward",
    "tm_inverse",
    "utm_zone",
    "latlon_to_utm",
    "utm_to_latlon",
    "geodesic_inverse",
]
