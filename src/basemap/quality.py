"""Data-quality reporting for basemaps.

A basemap under survey linework must earn its place: this module reports
ground sample distance, extents, band statistics, and nodata coverage, and
-- the feature that matters -- refuses to let a blurry basemap pass
silently. Given a target plat scale, it computes the GSD the imagery would
need and says plainly whether the orthomosaic meets it.

The scale rule: the smallest reliably discernible detail on paper is about
0.25 mm. At a scale denominator S (e.g. 600 for 1" = 50'), one paper
millimetre covers S millimetres on the ground, so the imagery needs
GSD <= 0.00025 * S metres to hold its own against the drawn linework.
"""

SCALE_DENOMINATORS = {
    # label -> denominator S (map units per paper unit)
    "1\"=10'": 120,
    "1\"=20'": 240,
    "1\"=30'": 360,
    "1\"=40'": 480,
    "1\"=50'": 600,
    "1\"=60'": 720,
    "1\"=100'": 1200,
    "1:500": 500,
    "1:1000": 1000,
    "1:2000": 2000,
}

PAPER_DETAIL_M = 0.00025  # 0.25 mm smallest reliable paper detail


def required_gsd(scale_denominator):
    """Coarsest GSD (metres) that still looks sharp at this scale."""
    return PAPER_DETAIL_M * scale_denominator


def check_scale(gsd_m, scale_label):
    """Check one plat scale against the basemap GSD.

    Returns a dict with ``required_gsd_m``, ``verdict`` ("PASS"/"WARN"),
    and a plain-language ``message``.
    """
    denom = SCALE_DENOMINATORS.get(scale_label)
    if denom is None:
        # allow raw "1:750" style labels
        try:
            denom = float(scale_label.split(":")[1])
        except (IndexError, ValueError):
            raise ValueError(
                f"unknown scale label {scale_label!r}; known: "
                f"{sorted(SCALE_DENOMINATORS)} or '1:N'")
    req = required_gsd(denom)
    ok = gsd_m <= req
    return {
        "scale": scale_label,
        "denominator": denom,
        "gsd_m": gsd_m,
        "required_gsd_m": req,
        "verdict": "PASS" if ok else "WARN",
        "message": (
            f"basemap GSD {gsd_m * 100:.1f} cm/px meets the "
            f"{req * 100:.1f} cm/px needed for {scale_label}"
            if ok else
            f"basemap GSD {gsd_m * 100:.1f} cm/px is coarser than the "
            f"{req * 100:.1f} cm/px needed for {scale_label} -- the "
            f"imagery will look soft under the linework; consider a "
            f"smaller-scale sheet or a higher-resolution flight"
        ),
    }


def quality_report(path, scales=("1\"=50'", "1\"=100'")):
    """Full quality report for a GeoTIFF basemap. Returns a plain dict."""
    from .raster import GeoTIFFRaster
    raster = GeoTIFFRaster(path)
    try:
        info = raster.info()
        gsd = max(info["gsd_x_m"], info["gsd_y_m"])
        non_square = abs(info["gsd_x_m"] - info["gsd_y_m"]) > 0.05 * gsd
        report = {
            "path": path,
            "dimensions_px": (info["width"], info["height"]),
            "bands": info["bands"],
            "bits_per_sample": info["bits_per_sample"],
            "compression": info["compression"],
            "tiled": info["tiled"],
            "crs": info["crs"],
            "gsd_m": {"x": info["gsd_x_m"], "y": info["gsd_y_m"]},
            "non_square_pixels": non_square,
            "extent_m": info["extent"],
            "nodata": info["nodata"],
            "nodata_fraction": raster.nodata_fraction(),
            "band_stats": raster.band_stats(),
            "overview_levels": info["overview_levels"],
            "scale_checks": [check_scale(gsd, s) for s in scales],
        }
        return report
    finally:
        raster.close()
