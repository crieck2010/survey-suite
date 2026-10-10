"""Angle adjustment by the method of condition equations.

Single geometric condition: the angles of a closed polygon must sum to
(n - 2) * 180 degrees (interior) or (n + 2) * 180 (exterior).

With B the 1 x n condition matrix (a row of ones), W the weight matrix,
and w the misclosure:

    v = -W^-1 B^T (B W^-1 B^T)^-1 w

With equal weights this reduces to distributing -w/n to every angle.
"""
from __future__ import annotations


def adjust_angles(angles: list[float], weights: list[float] | None = None,
                 n_sides: int | None = None,
                 interior: bool = True) -> tuple[list[float], list[float]]:
    """Adjust closed-polygon angles to satisfy the angle-sum condition.

    Args:
        angles: Observed angles in decimal degrees.
        weights: Relative weights (higher = more trusted). Defaults to
            equal weights.
        n_sides: Number of sides of the polygon; defaults to len(angles).
        interior: True for interior angles, False for exterior.

    Returns:
        (adjusted_angles, corrections) with corrections summing to
        -misclosure.
    """
    n = len(angles)
    if n == 0:
        raise ValueError("At least one angle is required")
    if weights is None:
        weights = [1.0] * n
    if len(weights) != n:
        raise ValueError("weights must match angles in length")
    if any(wt <= 0 for wt in weights):
        raise ValueError("weights must be positive")
    if n_sides is None:
        n_sides = n

    theoretical = (n_sides - 2) * 180.0 if interior else (n_sides + 2) * 180.0
    misclosure = sum(angles) - theoretical
    winv = [1.0 / wt for wt in weights]
    s = sum(winv)
    corrections = [-(wi / s) * misclosure for wi in winv]
    adjusted = [a + c for a, c in zip(angles, corrections)]
    return adjusted, corrections
