"""Loop misclosure, allowable error, and distribution of corrections.

Misclosure is distributed proportionally to the number of setups:
a point observed at setup ``j`` of ``n`` receives correction
``-misclosure * j / n``, so the adjusted loop closes exactly.
"""
from __future__ import annotations

import math

from .station import LevelPoint

# Allowable misclosure constants: millimetres per sqrt(kilometre).
ALLOWABLE_SPECS: dict[str, float] = {
    "first_order": 4.0,
    "second_order": 8.0,
    "third_order": 12.0,
}


def loop_misclosure(known_elevation: float, computed_elevation: float) -> float:
    """Loop misclosure = computed closing elevation - known elevation."""
    return computed_elevation - known_elevation


def allowable_misclosure(distance_km: float,
                         spec: str | float = "third_order") -> float:
    """Allowable loop misclosure in millimetres: C * sqrt(K).

    Args:
        distance_km: Total length of the level loop in kilometres.
        spec: A key of ``ALLOWABLE_SPECS`` or a custom C value
            (mm per sqrt(km)).
    """
    if isinstance(spec, str):
        if spec not in ALLOWABLE_SPECS:
            raise ValueError(f"Unknown spec {spec!r}; use one of "
                             f"{sorted(ALLOWABLE_SPECS)} or a number")
        c = ALLOWABLE_SPECS[spec]
    else:
        c = float(spec)
    if distance_km < 0:
        raise ValueError("Loop distance cannot be negative")
    return c * math.sqrt(distance_km)


def passes(misclosure_mm: float, allowable_mm: float) -> bool:
    """True if the absolute misclosure is within the allowable limit."""
    return abs(misclosure_mm) <= allowable_mm


def adjust_loop(points: list[LevelPoint], misclosure: float,
                n_setups: int) -> list[LevelPoint]:
    """Distribute the loop misclosure proportionally to setup count.

    Args:
        points: Output of :func:`reduce_levels`.
        misclosure: In the same unit as the elevations.
        n_setups: Number of instrument setups in the loop.

    Returns adjusted points; the closing point lands exactly on the
    known elevation.
    """
    if n_setups <= 0:
        raise ValueError("Number of setups must be positive")
    adjusted = []
    for p in points:
        correction = -misclosure * (p.setup_index / n_setups)
        adjusted.append(LevelPoint(p.station, p.elevation + correction,
                                   p.role, p.setup_index))
    return adjusted
