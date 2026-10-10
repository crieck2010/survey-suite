"""Datum definitions and inter-datum paths with accuracy metadata.

v1 scope decision (explicit): datum shifts between distinct datums are
*null approximations* (identity) carrying an estimated accuracy, NOT
survey-grade transformations. Every result exposes the path used so no
caller mistakes an approximate shift for control-quality work.

Sources:
  - NAD83(2011) vs modern WGS 84 differ ~1-2 m across CONUS:
    Penn State GEOG 862, "NAD 83 versus WGS 84"
    (https://www.e-education.psu.edu/geog862/node/1804).
  - NAD83(CORS96) -> NAD83(2011) shifts are centimetre-level: the 2011
    national readjustment moved CORS coordinates on average ~1.8 cm
    horizontally and ~-0.8 cm in ellipsoidal height (NC Geodetic Survey,
    "The National Adjustment of 2011",
    https://ncgs.state.nc.us/docs/2012-09-20_The_National_Adjustment_of_2011.pdf).
  - Current operational WGS 84 realization is G2296 (effective 2024-01-07,
    aligned to ITRF2020; supersedes G2139).
"""
from __future__ import annotations

from .errors import DatumError
from .models import DatumPath

#: Datums known to the registry.
DATUMS = (
    "NAD83(2011)",
    "NAD83(CORS96)",
    "WGS 84 (G2296)",
)

_WGS84_2011 = DatumPath(
    from_datum="NAD83(2011)",
    to_datum="WGS 84 (G2296)",
    method="null-approximation",
    accuracy_horizontal_m=2.0,
    region="CONUS",
    source=("Penn State GEOG 862: NAD83(2011) and modern WGS 84 realizations "
            "differ by roughly 1-2 m horizontally across CONUS; "
            "https://www.e-education.psu.edu/geog862/node/1804"),
    warning=("Approximate identity shift (<=~2 m horizontal in CONUS). "
             "Not suitable for survey control or legal boundary work; use a "
             "proper reference-frame transformation for those purposes."),
)

_CORS96_2011 = DatumPath(
    from_datum="NAD83(CORS96)",
    to_datum="NAD83(2011)",
    method="null-approximation",
    accuracy_horizontal_m=0.05,
    region="United States",
    source=("NC Geodetic Survey, 'The National Adjustment of 2011': mean "
            "horizontal shift of CORS positions ~1.8 cm, ellipsoidal height "
            "~-0.8 cm; "
            "https://ncgs.state.nc.us/docs/2012-09-20_The_National_Adjustment_of_2011.pdf"),
    warning=("Approximate identity shift; typical differences are ~2 cm, "
             "conservatively bounded at 5 cm. Not for survey control."),
)

_CORS96_WGS84 = DatumPath(
    from_datum="NAD83(CORS96)",
    to_datum="WGS 84 (G2296)",
    method="null-approximation",
    accuracy_horizontal_m=2.0,
    region="CONUS",
    source=("Composed from the NAD83(2011)<->WGS 84 (G2296) path above; "
            "dominated by the ~1-2 m NAD83/WGS 84 frame difference."),
    warning=("Approximate identity shift (<=~2 m horizontal in CONUS). "
             "Not suitable for survey control."),
)

_PATHS = {
    ("NAD83(2011)", "WGS 84 (G2296)"): _WGS84_2011,
    ("NAD83(CORS96)", "NAD83(2011)"): _CORS96_2011,
    ("NAD83(CORS96)", "WGS 84 (G2296)"): _CORS96_WGS84,
}


def _reverse(path: DatumPath) -> DatumPath:
    return DatumPath(
        from_datum=path.to_datum,
        to_datum=path.from_datum,
        method=path.method,
        accuracy_horizontal_m=path.accuracy_horizontal_m,
        region=path.region,
        source=path.source,
        warning=path.warning,
    )


def datum_path(from_datum: str, to_datum: str) -> DatumPath:
    """Return the DatumPath between two datums, with accuracy metadata.

    Same datum -> exact identity path (0.0 m). Distinct datums -> the
    documented null approximation. Unknown datums raise DatumError.
    """
    if from_datum not in DATUMS:
        raise DatumError("unknown datum: %r" % (from_datum,))
    if to_datum not in DATUMS:
        raise DatumError("unknown datum: %r" % (to_datum,))
    if from_datum == to_datum:
        return DatumPath(
            from_datum=from_datum,
            to_datum=to_datum,
            method="identity",
            accuracy_horizontal_m=0.0,
            region="n/a",
            source="same datum; no shift applied",
            warning="",
        )
    if (from_datum, to_datum) in _PATHS:
        return _PATHS[(from_datum, to_datum)]
    return _reverse(_PATHS[(to_datum, from_datum)])
