"""Helmert (similarity) datum transformations on ECEF coordinates.

Position-vector convention:

    X' = T + (1 + s) * R * X

with small rotations (rx, ry, rz) in arcseconds and scale s in ppm.
Negating all seven parameters gives the inverse transformation, which is
exact for the linearised form used here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class HelmertParams:
    """Seven Helmert parameters: translations (m), rotations (arcsec), scale (ppm)."""

    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0
    s_ppm: float = 0.0

    def inverse(self) -> "HelmertParams":
        """Parameters for the reverse transformation."""
        return HelmertParams(-self.dx, -self.dy, -self.dz,
                             -self.rx, -self.ry, -self.rz, -self.s_ppm)


def helmert_7param(x: float, y: float, z: float,
                   params: HelmertParams) -> tuple[float, float, float]:
    """Apply a 7-parameter Helmert transformation to an ECEF point."""
    arcsec = math.pi / (180.0 * 3600.0)
    rx, ry, rz = params.rx * arcsec, params.ry * arcsec, params.rz * arcsec
    s = 1.0 + params.s_ppm * 1e-6
    # Position-vector rotation matrix (small-angle form).
    xp = params.dx + s * (x - rz * y + ry * z)
    yp = params.dy + s * (rz * x + y - rx * z)
    zp = params.dz + s * (-ry * x + rx * y + z)
    return xp, yp, zp


def helmert_3param(x: float, y: float, z: float,
                   dx: float, dy: float, dz: float) -> tuple[float, float, float]:
    """Apply a 3-parameter (translation-only) Helmert transformation."""
    return helmert_7param(x, y, z, HelmertParams(dx=dx, dy=dy, dz=dz))
