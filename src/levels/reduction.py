"""Height-of-instrument reduction of differential level notes.

For each setup:  HI = elevation(back) + backsight
                 elevation(fore) = HI - foresight
"""
from __future__ import annotations

import math
from typing import NamedTuple

from .station import LevelPoint, Setup


class PageCheck(NamedTuple):
    """Arithmetic check of a level run."""

    bs_sum: float
    fs_sum: float
    check: float  # sum(BS) - sum(FS)
    actual: float  # last elevation - first elevation
    ok: bool


def reduce_levels(start_station: str, start_elevation: float,
                  setups: list[Setup]) -> list[LevelPoint]:
    """Reduce a level run by the height-of-instrument method.

    Returns the starting benchmark followed by every reduced point
    (turning points and sideshots), each tagged with its setup index.
    Raises ValueError if a backsight is taken on a station with no
    known elevation.
    """
    elevations: dict[str, float] = {start_station: start_elevation}
    points = [LevelPoint(start_station, start_elevation, "benchmark", 0)]

    for i, setup in enumerate(setups, start=1):
        if setup.backsight_station not in elevations:
            raise ValueError(
                f"Setup {i}: no elevation for backsight station "
                f"{setup.backsight_station!r}"
            )
        hi = elevations[setup.backsight_station] + setup.backsight
        fore_elev = hi - setup.foresight
        elevations[setup.foresight_station] = fore_elev
        points.append(LevelPoint(setup.foresight_station, fore_elev,
                                 "turning_point", i))
        for station, reading in setup.sideshots:
            points.append(LevelPoint(station, hi - reading, "sideshot", i))
    return points


def page_check(setups: list[Setup], start_elevation: float,
               end_elevation: float) -> PageCheck:
    """Arithmetic page check: sum(BS) - sum(FS) must equal last - first elevation."""
    bs_sum = sum(s.backsight for s in setups)
    fs_sum = sum(s.foresight for s in setups)
    check = bs_sum - fs_sum
    actual = end_elevation - start_elevation
    return PageCheck(bs_sum=bs_sum, fs_sum=fs_sum, check=check, actual=actual,
                     ok=math.isclose(check, actual, abs_tol=1e-9))
