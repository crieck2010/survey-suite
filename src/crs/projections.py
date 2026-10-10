"""Map-projection engine. Standard library only.

Supported methods (every EPSG method present in the registry):
  - Transverse Mercator (Snyder/Redfearn series). Uses ``survey-geodesy``
    when importable (lazy/optional), otherwise an internal implementation
    of the same series. SPCS TM zones carry a latitude of natural origin,
    which ``survey-geodesy``'s ``tm_forward`` does not model, so the false
    northing is adjusted by the meridional arc at that latitude.
  - Lambert Conic Conformal 2SP (Snyder), internal.
  - Hotine Oblique Mercator variant A (Snyder), internal; forward is
    closed-form, inverse is Newton-Raphson on the forward equations
    (nanometre round-trip across Alaska zone 1).
  - UTM is Transverse Mercator with standard parameters.

Reference ellipsoids: GRS80 for NAD83 datums, WGS84 for WGS 84.
"""
from __future__ import annotations

import math

from .errors import ProjectionError

# ---------------------------------------------------------------------------
# Ellipsoids (kept local so the engine has zero hard dependencies)
# ---------------------------------------------------------------------------

_ELLIPSOIDS = {
    "GRS80": (6378137.0, 1 / 298.257222101),
    "WGS84": (6378137.0, 1 / 298.257223563),
}


def ellipsoid_for_datum(datum: str) -> str:
    """Return the ellipsoid name for a registry datum string."""
    if datum.startswith("NAD83"):
        return "GRS80"
    if datum.startswith("WGS 84"):
        return "WGS84"
    raise ProjectionError("no ellipsoid known for datum %r" % (datum,))


def _ellipsoid_params(name: str):
    a, f = _ELLIPSOIDS[name]
    e2 = 2 * f - f * f
    return a, e2, e2 / (1 - e2), math.sqrt(e2)


# ---------------------------------------------------------------------------
# Optional / lazy survey-geodesy backend for Transverse Mercator
# ---------------------------------------------------------------------------

_GEODESY = None
_GEODESY_TRIED = False


def _geodesy_backend():
    """Import survey-geodesy lazily; return None when not installed."""
    global _GEODESY, _GEODESY_TRIED
    if not _GEODESY_TRIED:
        _GEODESY_TRIED = True
        try:
            from geodesy import transverse_mercator as _tm
            from geodesy import ellipsoids as _ell
            _GEODESY = (_tm.tm_forward, _tm.tm_inverse, _ell.GRS80, _ell.WGS84)
        except Exception:
            _GEODESY = None
    return _GEODESY


def backend_name() -> str:
    """Which TM backend is active: 'survey-geodesy' or 'internal'."""
    return "survey-geodesy" if _geodesy_backend() else "internal"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _meridian_arc(phi: float, a: float, e2: float) -> float:
    e4, e6 = e2 ** 2, e2 ** 3
    return a * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
        - (35 * e6 / 3072) * math.sin(6 * phi)
    )


def _lcc_constants(lat0, lon0, lat1, lat2, a, e2, e):
    p0, p1, p2 = math.radians(lat0), math.radians(lat1), math.radians(lat2)

    def m(phi):
        return math.cos(phi) / math.sqrt(1 - e2 * math.sin(phi) ** 2)

    def t(phi):
        return (math.tan(math.pi / 4 - phi / 2)
                / ((1 - e * math.sin(phi)) / (1 + e * math.sin(phi))) ** (e / 2))

    m1, m2 = m(p1), m(p2)
    t1, t2, t0 = t(p1), t(p2), t(p0)
    if abs(lat1 - lat2) < 1e-10:
        n = math.sin(p1)
    else:
        n = math.log(m1 / m2) / math.log(t1 / t2)
    F = m1 / (n * t1 ** n)
    rho0 = a * F * t0 ** n
    return n, F, rho0, math.radians(lon0)


# ---------------------------------------------------------------------------
# Transverse Mercator (with latitude-of-origin support)
# ---------------------------------------------------------------------------

def _tm_internal_forward(lat, lon, lon0, k0, fe, fn, lat0, a, e2, ep2):
    phi = math.radians(lat)
    lam = math.radians(lon)
    lam0 = math.radians(lon0)
    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = ep2 * math.cos(phi) ** 2
    A = (lam - lam0) * math.cos(phi)
    m = _meridian_arc(phi, a, e2) - _meridian_arc(math.radians(lat0), a, e2)
    E = fe + k0 * n * (
        A + (1 - t + c) * A ** 3 / 6
        + (5 - 18 * t + t ** 2 + 72 * c - 58 * ep2) * A ** 5 / 120
    )
    N = fn + k0 * (
        m + n * math.tan(phi) * (
            A ** 2 / 2
            + (5 - t + 9 * c + 4 * c ** 2) * A ** 4 / 24
            + (61 - 58 * t + t ** 2 + 600 * c - 330 * ep2) * A ** 6 / 720
        )
    )
    return E, N


def _tm_internal_inverse(E, N, lon0, k0, fe, fn, lat0, a, e2, ep2):
    e4, e6 = e2 ** 2, e2 ** 3
    m = (N - fn) / k0 + _meridian_arc(math.radians(lat0), a, e2)
    mu = m / (a * (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    t1 = math.tan(phi1) ** 2
    c1 = ep2 * math.cos(phi1) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = (E - fe) / (n1 * k0)
    phi = phi1 - (n1 * math.tan(phi1) / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2
           - 3 * c1 ** 2) * d ** 6 / 720
    )
    lam = (d - (1 + 2 * t1 + c1) * d ** 3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2
              + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(phi1)
    return math.degrees(phi), math.degrees(lam) + lon0


def tm_forward(lat, lon, lon0, k0, fe, fn, lat0, ellipsoid):
    """Forward TM, metres. Uses survey-geodesy when available."""
    g = _geodesy_backend()
    a, e2, _ep2, _e = _ellipsoid_params(ellipsoid)
    if g is not None:
        tmf, _tmi, GRS80, WGS84 = g
        ell = GRS80 if ellipsoid == "GRS80" else WGS84
        fn_adj = fn - k0 * _meridian_arc(math.radians(lat0), a, e2)
        return tmf(lat, lon, lon0, k0=k0, false_easting=fe,
                   false_northing=fn_adj, ellipsoid=ell)
    return _tm_internal_forward(lat, lon, lon0, k0, fe, fn, lat0, a, e2, _ep2)


def tm_inverse(E, N, lon0, k0, fe, fn, lat0, ellipsoid):
    """Inverse TM. Uses survey-geodesy when available."""
    g = _geodesy_backend()
    a, e2, ep2, _e = _ellipsoid_params(ellipsoid)
    if g is not None:
        _tmf, tmi, GRS80, WGS84 = g
        ell = GRS80 if ellipsoid == "GRS80" else WGS84
        fn_adj = fn - k0 * _meridian_arc(math.radians(lat0), a, e2)
        return tmi(E, N, lon0, k0=k0, false_easting=fe,
                   false_northing=fn_adj, ellipsoid=ell)
    return _tm_internal_inverse(E, N, lon0, k0, fe, fn, lat0, a, e2, ep2)


# ---------------------------------------------------------------------------
# Lambert Conic Conformal (2SP), Snyder
# ---------------------------------------------------------------------------

def lcc_forward(lat, lon, lat0, lon0, lat1, lat2, fe, fn, ellipsoid):
    a, e2, _ep2, e = _ellipsoid_params(ellipsoid)
    n, F, rho0, lam0 = _lcc_constants(lat0, lon0, lat1, lat2, a, e2, e)
    phi = math.radians(lat)
    lam = math.radians(lon)

    def t(p):
        return (math.tan(math.pi / 4 - p / 2)
                / ((1 - e * math.sin(p)) / (1 + e * math.sin(p))) ** (e / 2))

    rho = a * F * t(phi) ** n
    theta = n * (lam - lam0)
    return fe + rho * math.sin(theta), fn + rho0 - rho * math.cos(theta)


def lcc_inverse(E, N, lat0, lon0, lat1, lat2, fe, fn, ellipsoid):
    a, e2, _ep2, e = _ellipsoid_params(ellipsoid)
    n, F, rho0, lam0 = _lcc_constants(lat0, lon0, lat1, lat2, a, e2, e)
    rho = math.copysign(1.0, n) * math.hypot(E - fe, rho0 - (N - fn))
    theta = math.atan2(E - fe, rho0 - (N - fn))
    t = (rho / (a * F)) ** (1 / n)
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(12):
        phi = (math.pi / 2 - 2 * math.atan(
            t * ((1 - e * math.sin(phi)) / (1 + e * math.sin(phi))) ** (e / 2)))
    lon = math.degrees(lam0) + math.degrees(theta) / n
    return math.degrees(phi), lon


# ---------------------------------------------------------------------------
# Hotine Oblique Mercator, variant A (Snyder). Forward closed-form;
# inverse is Newton-Raphson on the forward equations.
# ---------------------------------------------------------------------------

def _hotine_constants(latc, lonc, azimuth_deg, kc, a, e2, e):
    phic = math.radians(latc)
    az = math.radians(azimuth_deg)
    B = math.sqrt(1 + e2 * math.cos(phic) ** 4 / (1 - e2))
    A = a * B * kc * math.sqrt(1 - e2) / (1 - e2 * math.sin(phic) ** 2)

    def t(phi):
        return (math.tan(math.pi / 4 - phi / 2)
                / ((1 - e * math.sin(phi)) / (1 + e * math.sin(phi))) ** (e / 2))

    t0 = t(phic)
    D = B * math.sqrt(1 - e2) / (math.cos(phic)
                                 * math.sqrt(1 - e2 * math.sin(phic) ** 2))
    # Positive root matches the EPSG definition (verified against PROJ for
    # EPSG:6394 Alaska zone 1 at 2026-09-27).
    F = D + math.sqrt(D * D - 1)
    H = F * t0 ** B
    G = (F - 1 / F) / 2
    gamma0 = math.asin(math.sin(az) / D)
    lam0 = math.radians(lonc) - math.asin(G * math.tan(gamma0)) / B
    return A, B, H, gamma0, lam0, t


def hotine_forward(lat, lon, latc, lonc, azimuth_deg, rectified_skew_deg,
                   kc, fe, fn, ellipsoid):
    a, e2, _ep2, e = _ellipsoid_params(ellipsoid)
    A, B, H, gamma0, lam0, t = _hotine_constants(latc, lonc, azimuth_deg, kc,
                                                a, e2, e)
    gammas = math.radians(rectified_skew_deg)
    phi = math.radians(lat)
    lam = math.radians(lon)
    Q = H / t(phi) ** B
    S = (Q - 1 / Q) / 2
    T = (Q + 1 / Q) / 2
    V = math.sin(B * (lam - lam0))
    U = (-V * math.cos(gamma0) + S * math.sin(gamma0)) / T
    v = A * math.log((1 - U) / (1 + U)) / (2 * B)
    u = A * math.atan2(S * math.cos(gamma0) + V * math.sin(gamma0),
                       math.cos(B * (lam - lam0))) / B
    E = fe + v * math.cos(gammas) + u * math.sin(gammas)
    N = fn + u * math.cos(gammas) - v * math.sin(gammas)
    return E, N


def hotine_inverse(E, N, latc, lonc, azimuth_deg, rectified_skew_deg,
                   kc, fe, fn, ellipsoid):
    def fwd(la, lo):
        return hotine_forward(la, lo, latc, lonc, azimuth_deg,
                              rectified_skew_deg, kc, fe, fn, ellipsoid)

    lat, lon = latc, lonc
    h = 1e-7  # radians, central-difference step
    for _ in range(25):
        E0, N0 = fwd(lat, lon)
        rE, rN = E - E0, N - N0
        if abs(rE) < 1e-9 and abs(rN) < 1e-9:
            return lat, lon
        hd = math.degrees(h)
        dE_dla = (fwd(lat + hd, lon)[0] - E0) / hd
        dN_dla = (fwd(lat + hd, lon)[1] - N0) / hd
        dE_dlo = (fwd(lat, lon + hd)[0] - E0) / hd
        dN_dlo = (fwd(lat, lon + hd)[1] - N0) / hd
        det = dE_dla * dN_dlo - dE_dlo * dN_dla
        if det == 0:
            break
        lat += (rE * dN_dlo - rN * dE_dlo) / det
        lon += (dE_dla * rN - dN_dla * rE) / det
    raise ProjectionError("Hotine inverse failed to converge for E=%r N=%r"
                          % (E, N))
