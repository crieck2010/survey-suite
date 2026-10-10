"""survey-adjust: least-squares adjustment engine for surveying.

Pure-Python, dependency-free engine: weighted least-squares adjustment of
differential level networks, angle adjustment by condition equations, and
a chi-square global model test. No UI, no I/O -- import it from any
application or script.
"""

__version__ = "0.1.0"

from .conditions import adjust_angles
from .level_net import (
    AdjustedPoint,
    DiffObservation,
    NetAdjustment,
    adjust_level_net,
)
from .matrices import inverse, matmul, matvec, solve, transpose
from .stats import chi_square_critical, global_test

__all__ = [
    "__version__",
    "DiffObservation",
    "AdjustedPoint",
    "NetAdjustment",
    "adjust_level_net",
    "adjust_angles",
    "chi_square_critical",
    "global_test",
    "matmul",
    "matvec",
    "transpose",
    "inverse",
    "solve",
]
