"""Traverse computation: run legs, check closure, distribute error (Compass/Bowditch).

A traverse leg is defined by a forward azimuth and a horizontal distance.
Use :func:`azimuths_from_turned_angles` to convert field-observed turned
angles into azimuths first.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple

from .angles import normalize_angle
from .forward import forward
from .point import Point


@dataclass(frozen=True)
class Leg:
    """One traverse leg: forward azimuth (deg, clockwise from north) and distance."""

    azimuth: float
    distance: float


class LinearMisclosure(NamedTuple):
    """Linear misclosure of a (closed) traverse."""

    d_northing: float
    d_easting: float
    linear_error: float


def azimuths_from_turned_angles(start_azimuth: float, angles: list[float],
                                turn: str = "right") -> list[float]:
    """Convert a sequence of turned angles to forward azimuths.

    At each station: backsight_az = (prev_forward_az + 180) % 360, then
    next_forward_az = backsight_az +/- angle (plus for a right turn).
    """
    if turn not in ("right", "left"):
        raise ValueError("turn must be 'right' or 'left'")
    azimuths = [normalize_angle(start_azimuth)]
    for angle in angles:
        back = (azimuths[-1] + 180.0) % 360.0
        nxt = back + angle if turn == "right" else back - angle
        azimuths.append(normalize_angle(nxt))
    return azimuths


def run_traverse(start: Point, legs: list[Leg],
                 names: list[str] | None = None) -> list[Point]:
    """Run a traverse from ``start``; returns [start, p1, p2, ...]."""
    points = [start]
    for i, leg in enumerate(legs):
        name = names[i] if names and i < len(names) else ""
        points.append(forward(points[-1], leg.azimuth, leg.distance, name=name))
    return points


def angular_misclosure(angles: list[float], n_sides: int, interior: bool = True) -> float:
    """Angular misclosure of a closed polygon traverse (decimal degrees).

    Sum of interior angles should equal (n - 2) * 180; exterior (n + 2) * 180.
    Returns observed_sum - theoretical_sum.
    """
    theoretical = (n_sides - 2) * 180.0 if interior else (n_sides + 2) * 180.0
    return sum(angles) - theoretical


def linear_misclosure(start: Point, end_computed: Point) -> LinearMisclosure:
    """Linear misclosure vector between the known closing point and the computed one."""
    d_n = end_computed.northing - start.northing
    d_e = end_computed.easting - start.easting
    return LinearMisclosure(d_northing=d_n, d_easting=d_e,
                            linear_error=math.hypot(d_n, d_e))


def relative_precision(linear_error: float, total_length: float) -> tuple[float, str]:
    """Return (ratio, '1:X' string) for linear_error over total traverse length."""
    if total_length <= 0:
        raise ValueError("Total traverse length must be positive")
    if linear_error <= 0:
        return float("inf"), "1:inf (perfect closure)"
    ratio = total_length / linear_error
    return ratio, f"1:{ratio:,.0f}"


def compass_adjust(start: Point, legs: list[Leg],
                   names: list[str] | None = None) -> list[Point]:
    """Bowditch (compass rule) adjustment of a closed-loop traverse.

    Distributes the linear misclosure proportionally to leg length so the
    traverse closes exactly on ``start``. Returns [start, p1, ..., start].
    """
    raw = run_traverse(start, legs)
    mis = linear_misclosure(start, raw[-1])
    total = sum(leg.distance for leg in legs)
    if total <= 0:
        raise ValueError("Total traverse length must be positive")

    adjusted = [start]
    corr_n = corr_e = 0.0
    for i, leg in enumerate(legs):
        corr_n += -mis.d_northing * (leg.distance / total)
        corr_e += -mis.d_easting * (leg.distance / total)
        name = names[i] if names and i < len(names) else ""
        adjusted.append(Point(
            northing=raw[i + 1].northing + corr_n,
            easting=raw[i + 1].easting + corr_e,
            name=name,
            elevation=raw[i + 1].elevation,
        ))
    return adjusted
