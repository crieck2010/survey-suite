"""survey-levels: differential leveling engine for surveying.

Pure-Python, dependency-free engine: height-of-instrument reduction of
level notes, arithmetic page checks, loop misclosure against standard
allowable errors, and proportional distribution of corrections. No UI,
no I/O -- import it from any application or script.
"""

__version__ = "0.1.0"

from .adjustment import (
    ALLOWABLE_SPECS,
    adjust_loop,
    allowable_misclosure,
    loop_misclosure,
    passes,
)
from .reduction import PageCheck, page_check, reduce_levels
from .station import LevelPoint, Setup

__all__ = [
    "__version__",
    "Setup",
    "LevelPoint",
    "PageCheck",
    "reduce_levels",
    "page_check",
    "loop_misclosure",
    "allowable_misclosure",
    "ALLOWABLE_SPECS",
    "passes",
    "adjust_loop",
]
