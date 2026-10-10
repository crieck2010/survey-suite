"""CRS discipline for basemaps.

v1 rule, stated plainly: the basemap CRS must match the project CRS, or the
engine fails loud. There is no silent reprojection -- a basemap drawn in the
wrong datum under survey linework is worse than no basemap. Reprojection is
a defined future extension (see docs/INTEROP.md), not something v1 guesses
at.

CRS identity is compared by EPSG code. The built-in table below is
deliberately small and honest: codes outside it are reported raw and the
comparison still works on the numbers.
"""

import re

from .errors import CRSMismatch, NoGeoreferencing
from .geo import (parse_geokeys, geokey_summary, GT_MODEL_TYPE,
                  GEOGRAPHIC_TYPE, PROJECTED_CRS_TYPE)


def _utm_table():
    table = {}
    for zone in range(1, 61):
        code = 32600 + zone
        table[code] = (
            f"WGS 84 / UTM zone {zone}N",
            f"+proj=utm +zone={zone} +datum=WGS84 +units=m +no_defs +type=crs",
        )
        code = 32700 + zone
        table[code] = (
            f"WGS 84 / UTM zone {zone}S",
            f"+proj=utm +zone={zone} +datum=WGS84 +units=m +no_defs +type=crs",
        )
    for zone in range(1, 61):
        code = 26900 + zone
        table[code] = (
            f"NAD83 / UTM zone {zone}N",
            f"+proj=utm +zone={zone} +datum=NAD83 +units=m +no_defs +type=crs",
        )
    return table


_EPSG_TABLE = _utm_table()
_EPSG_TABLE.update({
    4326: ("WGS 84",
            "+proj=longlat +datum=WGS84 +no_defs +type=crs"),
    4269: ("NAD83",
            "+proj=longlat +datum=NAD83 +no_defs +type=crs"),
    3857: ("WGS 84 / Pseudo-Mercator",
            "+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 "
            "+x_0=0 +y_0=0 +k=1 +units=m +no_defs +type=crs"),
    # NAD83 New York State Plane (US survey feet) -- the zones Charlie
    # works in. Metre variants are 32100+zone; add on request.
    2260: ("NAD83 / New York Long Island (ftUS)",
            "+proj=lcc +lat_1=41.0333333333333 +lat_2=40.6666666666667 "
            "+lat_0=40.1666666666667 +lon_0=-74 +x_0=300000.0000000001 "
            "+y_0=0 +datum=NAD83 +units=us-ft +no_defs +type=crs"),
    2261: ("NAD83 / New York East (ftUS)",
            "+proj=tmerc +lat_0=0 +lon_0=-74.3333333333333 +k=0.9999 "
            "+x_0=152400.3048006096 +y_0=0 +datum=NAD83 +units=us-ft "
            "+no_defs +type=crs"),
    2262: ("NAD83 / New York Central (ftUS)",
            "+proj=tmerc +lat_0=0 +lon_0=-76.5833333333333 +k=0.9999 "
            "+x_0=152400.3048006096 +y_0=0 +datum=NAD83 +units=us-ft "
            "+no_defs +type=crs"),
    2263: ("NAD83 / New York West (ftUS)",
            "+proj=tmerc +lat_0=0 +lon_0=-78.5833333333333 +k=0.9999 "
            "+x_0=152400.3048006096 +y_0=0 +datum=NAD83 +units=us-ft "
            "+no_defs +type=crs"),
})


class CRSInfo:
    """What we know about a raster's CRS."""

    def __init__(self, epsg, kind, summary):
        self.epsg = epsg            # int or None
        self.kind = kind            # "projected" | "geographic" | "unknown"
        self.summary = summary      # human string

    @property
    def name(self):
        if self.epsg and self.epsg in _EPSG_TABLE:
            return _EPSG_TABLE[self.epsg][0]
        return "unknown CRS"

    @property
    def proj4(self):
        if self.epsg and self.epsg in _EPSG_TABLE:
            return _EPSG_TABLE[self.epsg][1]
        return None

    def __str__(self):
        if self.epsg:
            return f"EPSG:{self.epsg} ({self.name})"
        return self.summary

    def __repr__(self):
        return f"CRSInfo(epsg={self.epsg!r}, kind={self.kind!r})"


def crs_from_ifd(ifd, path="<memory>"):
    """Describe the CRS from an IFD's GeoKeys. Raises NoGeoreferencing
    when the file carries no CRS at all."""
    keys = parse_geokeys(ifd)
    if not keys:
        raise NoGeoreferencing(
            f"{path}: no GeoKey directory -- CRS unknown")
    epsg = keys.get(PROJECTED_CRS_TYPE) or keys.get(GEOGRAPHIC_TYPE)
    epsg = int(epsg) if epsg else None
    model = keys.get(GT_MODEL_TYPE, 0)
    kind = {1: "projected", 2: "geographic"}.get(model, "unknown")
    return CRSInfo(epsg, kind, geokey_summary(keys))


_EPSG_RE = re.compile(r"EPSG\s*:?\s*(\d+)", re.IGNORECASE)


def epsg_from_string(s):
    """Pull an EPSG code out of a CRS string like ``"EPSG:26918"`` or
    ``"NAD83 / UTM zone 18N (EPSG 26918)"``. Returns None when no code is
    found."""
    if s is None:
        return None
    m = _EPSG_RE.search(str(s))
    return int(m.group(1)) if m else None


def ensure_crs_match(basemap_crs, project_crs, path="<memory>"):
    """Fail loud unless the basemap CRS matches the project CRS.

    ``basemap_crs`` is a CRSInfo; ``project_crs`` is the project's CRS
    string (as carried on the survey-field job, e.g.
    ``"NAD83(2011) / UTM zone 18N"`` or ``"EPSG:26918"``). Returns the
    matched EPSG code. Raises CRSMismatch with remediation guidance.
    """
    if basemap_crs.epsg is None:
        raise CRSMismatch(
            f"{path}: basemap CRS has no EPSG code ({basemap_crs.summary}) "
            f"-- cannot verify it matches the project CRS. Re-export the "
            f"orthomosaic with an explicit projected CRS.")
    proj_epsg = epsg_from_string(project_crs)
    if proj_epsg is None:
        raise CRSMismatch(
            f"{path}: project CRS {project_crs!r} carries no EPSG code -- "
            f"pass an explicit EPSG (e.g. \"EPSG:26918\") so the basemap "
            f"CRS ({basemap_crs}) can be checked.")
    if proj_epsg != basemap_crs.epsg:
        raise CRSMismatch(
            f"{path}: CRS mismatch -- basemap is {basemap_crs}, project is "
            f"EPSG:{proj_epsg}. v1 does not reproject; re-export the "
            f"orthomosaic in the project CRS (QGIS: Raster > Projections > "
            f"Warp, or gdalwarp -t_srs EPSG:{proj_epsg}).")
    return proj_epsg
