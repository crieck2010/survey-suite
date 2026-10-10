"""Inverse geodetic problem on the ellipsoid (Vincenty, 1975).

Given two geographic positions, computes the geodesic distance and the
forward/reverse azimuths. Accurate to ~0.5 mm on WGS84; nearly antipodal
points may fail to converge (ValueError).
"""
from __future__ import annotations

import math

from .ellipsoids import Ellipsoid, WGS84


def geodesic_inverse(lat1_deg: float, lon1_deg: float,
                     lat2_deg: float, lon2_deg: float,
                     ellipsoid: Ellipsoid = WGS84
                     ) -> tuple[float, float, float]:
    """Return (distance_m, fwd_azimuth_deg, rev_azimuth_deg).

    The forward azimuth is measured at point 1 toward point 2; the reverse
    azimuth is measured at point 2 back toward point 1.
    """
    a, f, b = ellipsoid.a, ellipsoid.f, ellipsoid.b
    phi1, phi2 = math.radians(lat1_deg), math.radians(lat2_deg)
    big_l = math.radians(lon2_deg - lon1_deg)

    u1 = math.atan((1 - f) * math.tan(phi1))
    u2 = math.atan((1 - f) * math.tan(phi2))
    sin_u1, cos_u1 = math.sin(u1), math.cos(u1)
    sin_u2, cos_u2 = math.sin(u2), math.cos(u2)

    lam = big_l
    for _ in range(200):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sig = math.hypot(cos_u2 * sin_lam,
                             cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam)
        if sin_sig == 0.0:
            return 0.0, 0.0, 0.0  # coincident points
        cos_sig = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = math.atan2(sin_sig, cos_sig)
        sin_alpha = cos_u1 * cos_u2 * sin_lam / sin_sig
        cos2_alpha = 1 - sin_alpha ** 2
        cos_2sigm = (cos_sig - 2 * sin_u1 * sin_u2 / cos2_alpha
                     if cos2_alpha > 1e-15 else 0.0)
        c = f / 16 * cos2_alpha * (4 + f * (4 - 3 * cos2_alpha))
        lam_new = (big_l + (1 - c) * f * sin_alpha *
                   (sigma + c * sin_sig *
                    (cos_2sigm + c * cos_sig * (2 * cos_2sigm ** 2 - 1))))
        if abs(lam_new - lam) < 1e-12:
            lam = lam_new
            break
        lam = lam_new
    else:
        raise ValueError("Vincenty failed to converge (nearly antipodal points?)")

    u2_ = cos2_alpha * (a * a - b * b) / (b * b)
    big_a = 1 + u2_ / 16384 * (4096 + u2_ * (-768 + u2_ * (320 - 175 * u2_)))
    big_b = u2_ / 1024 * (256 + u2_ * (-128 + u2_ * (74 - 47 * u2_)))
    d_sig = (big_b * sin_sig *
             (cos_2sigm + big_b / 4 *
              (cos_sig * (2 * cos_2sigm ** 2 - 1)
               - big_b / 6 * cos_2sigm * (4 * sin_sig ** 2 - 3) *
               (4 * cos_2sigm ** 2 - 3))))
    distance = b * big_a * (sigma - d_sig)

    fwd_az = math.degrees(math.atan2(cos_u2 * math.sin(lam),
                                     cos_u1 * sin_u2 - sin_u1 * cos_u2 * math.cos(lam)))
    # alpha2 below is the azimuth of the geodesic at point 2 in the direction
    # of travel; the reverse (back) azimuth points from 2 back to 1.
    alpha2 = math.degrees(math.atan2(cos_u1 * math.sin(lam),
                                     -sin_u1 * cos_u2 + cos_u1 * sin_u2 * math.cos(lam)))
    return distance, fwd_az % 360.0, (alpha2 + 180.0) % 360.0
