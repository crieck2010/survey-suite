"""Data models for differential leveling: setups and reduced points."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Setup:
    """One instrument setup in a level run.

    Attributes:
        backsight_station: Name of the point the backsight is taken on
            (a benchmark or the previous turning point).
        backsight: Backsight rod reading (+).
        foresight_station: Name of the point the foresight is taken on
            (a turning point or closing benchmark).
        foresight: Foresight rod reading (-).
        sideshots: Optional intermediate sights ``((station, reading), ...)``
            taken from this setup; they do not propagate the level line.
        distance_km: Optional sight distance for this setup, in kilometres,
            used for distance-weighted checks.
    """

    backsight_station: str
    backsight: float
    foresight_station: str
    foresight: float
    sideshots: tuple[tuple[str, float], ...] = ()
    distance_km: float = 0.0


@dataclass(frozen=True)
class LevelPoint:
    """A reduced level point.

    Attributes:
        station: Point name.
        elevation: Computed elevation.
        role: One of ``"benchmark"``, ``"turning_point"``, ``"sideshot"``.
        setup_index: 0-based index of the setup that produced this point
            (0 for the starting benchmark); used when distributing
            misclosure corrections.
    """

    station: str
    elevation: float
    role: str = "turning_point"
    setup_index: int = 0
