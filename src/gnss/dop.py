"""Dilution of precision from satellite geometry.

Given line-of-sight unit vectors to the tracked satellites, the
cofactor matrix Q = (A^T A)^-1 (A has one row per satellite:
[e, n, u, 1]) yields GDOP/PDOP/HDOP/VDOP/TDOP from its diagonal.

Pass unit vectors in a local ENU frame (see
``coords.unit_vectors_to_enu``) for the horizontal/vertical split to be
meaningful. Needs at least 4 satellites with non-degenerate geometry.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Dop:
    gdop: float
    pdop: float
    hdop: float
    vdop: float
    tdop: float


def _invert_4x4(m: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan inverse with partial pivoting (raises on singular)."""
    n = 4
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)]
           for i, row in enumerate(m)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-12:
            raise ValueError("Singular geometry: cannot compute DOP")
        aug[col], aug[piv] = aug[piv], aug[col]
        div = aug[col][col]
        aug[col] = [v / div for v in aug[col]]
        for r in range(n):
            if r != col and aug[r][col] != 0.0:
                factor = aug[r][col]
                aug[r] = [a - factor * b
                          for a, b in zip(aug[r], aug[col])]
    return [row[n:] for row in aug]


def dop_from_unit_vectors(unit_vectors: list[tuple[float, float, float]]
                          ) -> Dop:
    """Compute DOP from line-of-sight unit vectors (ENU frame)."""
    if len(unit_vectors) < 4:
        raise ValueError("Need at least 4 satellites for DOP")
    # Normal matrix N = A^T A, A rows are (e, n, u, 1).
    nmat = [[0.0] * 4 for _ in range(4)]
    for e, north, u in unit_vectors:
        row = (e, north, u, 1.0)
        for i in range(4):
            for j in range(4):
                nmat[i][j] += row[i] * row[j]
    q = _invert_4x4(nmat)
    qe, qn, qu, qt = q[0][0], q[1][1], q[2][2], q[3][3]
    return Dop(
        gdop=math.sqrt(qe + qn + qu + qt),
        pdop=math.sqrt(qe + qn + qu),
        hdop=math.sqrt(qe + qn),
        vdop=math.sqrt(qu),
        tdop=math.sqrt(qt),
    )


def dop_quality(dop: Dop) -> str:
    """Rough survey-grade label from PDOP."""
    if dop.pdop < 2:
        return "excellent"
    if dop.pdop < 4:
        return "good"
    if dop.pdop < 6:
        return "moderate"
    return "poor"
