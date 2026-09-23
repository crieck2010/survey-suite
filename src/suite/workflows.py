"""Cross-engine integration workflows.

Each workflow composes two or more survey-suite engines into a task a
field crew or office tech actually performs. The engines stay
independent -- these are thin orchestration, no duplicated math -- so
interoperability is demonstrated, not just documented.

Scaling: workflows stream where the engines stream (NMEA logs,
point chunks) and rasterize early (point cloud -> grid -> raster),
following each engine's scaling guidance.
"""
from __future__ import annotations

from typing import Iterable, Optional


def dem_volume_workflow(points, origin_x: float, origin_y: float,
                        pixel_size: float, width: int, height: int,
                        base_elevation: float, cell_size: float = 2.0,
                        threshold: float = 0.15,
                        crs: str = "") -> dict:
    """Point cloud -> classified ground -> DTM raster -> cut/fill volume.

    Engines: survey-pointcloud (classify, grid) + survey-raster (Raster).
    Returns ``{"ground_count", "dtm", "cut", "fill", "net"}`` where
    ``dtm`` is a ``survey_raster.Raster`` ready for further analysis
    (hillshade, contours, export).
    """
    from pointcloud import classify_ground_grid, grid_minimum, volume_grid, GROUND
    from raster import Raster

    ground = [p for p in classify_ground_grid(points, cell_size, threshold)
              if p.classification == GROUND]
    grid = grid_minimum(ground, origin_x, origin_y, pixel_size, width, height)
    transform = (origin_x, pixel_size, 0.0, origin_y, 0.0, pixel_size)
    dtm = Raster(data=grid, transform=transform, crs=crs, nodata=float("nan"))
    cut, fill, net = volume_grid(grid, base_elevation, pixel_size ** 2)
    return {"ground_count": len(ground), "dtm": dtm,
            "cut": cut, "fill": fill, "net": net}


def level_to_adjustment_workflow(start_station: str, start_elevation: float,
                                 setups, sigma: float = 0.003) -> dict:
    """Field notes -> reduction -> page check -> least-squares network.

    Engines: survey-levels (HI reduction, page check) + survey-adjust
    (weighted parametric adjustment). Each setup's backsight->foresight
    elevation difference becomes a ``DiffObservation``; the starting
    benchmark is the held datum.

    Returns ``{"points", "page_check", "adjustment"}``.
    """
    from adjust import DiffObservation, adjust_level_net
    from levels import page_check, reduce_levels

    points = reduce_levels(start_station, start_elevation, list(setups))
    line = [p for p in points if p.role in ("benchmark", "turning_point")]
    check = page_check(list(setups), start_elevation, line[-1].elevation)
    observations = [
        DiffObservation(from_station=line[i].station,
                        to_station=line[i + 1].station,
                        delta_h=line[i + 1].elevation - line[i].elevation,
                        sigma=sigma)
        for i in range(len(line) - 1)
    ]
    adjustment = adjust_level_net(observations,
                                  fixed={start_station: start_elevation})
    return {"points": points, "page_check": check, "adjustment": adjustment}


def gnss_cogo_control_workflow(nmea_lines: Iterable[str],
                               control_name: str = "CTRL-1") -> dict:
    """NMEA log -> session mean -> UTM -> COGO control point.

    Engines: survey-gnss (streaming parse, Welford session) +
    survey-geodesy (lat/lon to UTM) + survey-cogo (plane Point).

    Returns ``{"mean_lat", "mean_lon", "mean_h", "easting", "northing",
    "zone", "hemisphere", "control_point", "accuracy_m", "n_fixes"}``.
    Raises ValueError if no valid GGA fixes are found.
    """
    from cogo import Point as CogoPoint
    from geodesy import latlon_to_utm
    from gnss import Fix, GgaFix, Session, iter_sentences

    session = Session()
    for sentence in iter_sentences(nmea_lines):
        if isinstance(sentence, GgaFix):
            fix = Fix.from_gga(sentence)
            if fix is not None:
                session.add(fix)
    if session.count == 0:
        raise ValueError("No valid GGA fixes in input")
    lat, lon, h = session.mean_position()
    easting, northing, zone, hemi = latlon_to_utm(lat, lon)
    control = CogoPoint(northing=northing, easting=easting,
                        name=control_name, elevation=h)
    return {"mean_lat": lat, "mean_lon": lon, "mean_h": h,
            "easting": easting, "northing": northing,
            "zone": zone, "hemisphere": hemi,
            "control_point": control,
            "accuracy_m": session.horizontal_accuracy_metres(),
            "n_fixes": session.count}
