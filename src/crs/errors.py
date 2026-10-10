"""Exceptions for the survey-crs engine."""
from __future__ import annotations


class CrsError(Exception):
    """Base class for all survey-crs errors."""


class UnknownEpsg(CrsError):
    """Raised when an EPSG code is not in the registry."""


class UnknownState(CrsError):
    """Raised when a state name/abbreviation cannot be resolved."""


class ProjectionError(CrsError):
    """Raised when a projection computation fails to converge."""


class DatumError(CrsError):
    """Raised when no datum path exists between two datums."""
