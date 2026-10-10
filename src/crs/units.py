"""Linear unit conversions. Standard library only.

The US survey foot is defined by statute as exactly 1200/3937 metres
(NIST Handbook 44; adopted for SPCS by NOAA Manual NOS NGS 5).
"""
from __future__ import annotations

#: Exact metres per US survey foot (1200/3937).
US_FOOT_M: float = 1200.0 / 3937.0

#: Exact US survey feet per metre (3937/1200).
M_PER_US_FOOT: float = 3937.0 / 1200.0

#: Exact metres per international foot.
INTL_FOOT_M: float = 0.3048

#: Unit codes used by the registry.
UNIT_METRE = "m"
UNIT_US_FOOT = "ftUS"
UNIT_INTL_FOOT = "ft"
UNIT_DEGREE = "deg"


def m_to_ftus(metres: float) -> float:
    """Convert metres to US survey feet (exact 3937/1200 factor)."""
    return metres * M_PER_US_FOOT


def ftus_to_m(feet: float) -> float:
    """Convert US survey feet to metres (exact 1200/3937 factor)."""
    return feet * US_FOOT_M


def m_to_ft(metres: float) -> float:
    """Convert metres to international feet (exact 0.3048 factor)."""
    return metres / INTL_FOOT_M


def ft_to_m(feet: float) -> float:
    """Convert international feet to metres (exact 0.3048 factor)."""
    return feet * INTL_FOOT_M


def to_metres(value: float, unit: str) -> float:
    """Convert a linear value in `unit` to metres."""
    if unit == UNIT_METRE:
        return value
    if unit == UNIT_US_FOOT:
        return ftus_to_m(value)
    if unit == UNIT_INTL_FOOT:
        return ft_to_m(value)
    raise ValueError("unknown linear unit: %r" % (unit,))


def from_metres(value: float, unit: str) -> float:
    """Convert a metre value to `unit`."""
    if unit == UNIT_METRE:
        return value
    if unit == UNIT_US_FOOT:
        return m_to_ftus(value)
    if unit == UNIT_INTL_FOOT:
        return m_to_ft(value)
    raise ValueError("unknown linear unit: %r" % (unit,))
