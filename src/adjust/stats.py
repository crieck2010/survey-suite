"""Statistical validation of an adjustment.

Global model test: H0: sigma0^2 = 1 (the a priori stochastic model is
correct). Test statistic T = dof * s0^2 follows chi-square with dof
degrees of freedom under H0. H0 is rejected when T exceeds the upper
(1 - alpha) critical value.

Critical values use the Wilson-Hilferty approximation, accurate enough
for a screening test without tabulated values.
"""
from __future__ import annotations

import math

_Z = {0.10: 1.2815516, 0.05: 1.6448536, 0.025: 1.9599640, 0.01: 2.3263479}


def chi_square_critical(dof: int, alpha: float = 0.05) -> float:
    """Upper-tail chi-square critical value (Wilson-Hilferty approximation)."""
    if dof <= 0:
        raise ValueError("Degrees of freedom must be positive")
    if alpha not in _Z:
        raise ValueError(f"alpha must be one of {sorted(_Z)}")
    z = _Z[alpha]
    t = 1.0 - 2.0 / (9.0 * dof) + z * math.sqrt(2.0 / (9.0 * dof))
    return dof * t ** 3


def global_test(dof: int, sigma0_sq: float,
                alpha: float = 0.05) -> tuple[bool, float, float]:
    """Chi-square global test of the adjustment's variance factor.

    Returns (passed, statistic, critical_value). ``passed`` is True when
    the statistic does not exceed the critical value.
    """
    if dof <= 0:
        raise ValueError("Degrees of freedom must be positive")
    statistic = dof * sigma0_sq
    critical = chi_square_critical(dof, alpha)
    return statistic <= critical, statistic, critical
