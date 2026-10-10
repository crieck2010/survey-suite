"""Least-squares adjustment of a differential level network.

Parametric model: for each observed elevation difference between two
stations, the observation equation is

    delta_h + v = E_to - E_from

Unknowns are station elevations; at least one station must be held fixed
as the datum. With k observations and m free stations:

    x_hat = (A^T W A)^-1 A^T W L        (L = observed - computed)
    v     = A x_hat - L                  (residuals)
    s0^2  = v^T W v / (k - m)            (reference variance)
    Cx    = s0^2 (A^T W A)^-1            (covariance of unknowns)

Weights default to 1/sigma^2 from each observation's stated std. dev.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .matrices import inverse, matmul, matvec, transpose, zeros


@dataclass(frozen=True)
class DiffObservation:
    """One observed elevation difference.

    Attributes:
        from_station: Station the backsight was on.
        to_station: Station the foresight was on.
        delta_h: Observed elevation difference (to minus from).
        sigma: A priori standard deviation of the observation
            (same unit as delta_h). Drives the weight: w = 1/sigma^2.
    """

    from_station: str
    to_station: str
    delta_h: float
    sigma: float = 1.0


@dataclass(frozen=True)
class AdjustedPoint:
    """An adjusted station elevation with its standard deviation."""

    station: str
    elevation: float
    std_dev: float | None  # None when there is no redundancy (dof = 0)


@dataclass(frozen=True)
class NetAdjustment:
    """Result of a level-net least-squares adjustment."""

    points: list[AdjustedPoint]      # free stations, then fixed (std_dev 0.0)
    residuals: list[float]          # v, same order as the observations
    adjusted_observations: list[float]  # observed + residual
    sigma0: float | None            # a posteriori reference std. dev.
    dof: int                        # degrees of freedom (k - m)


def _reachable_stations(observations: list[DiffObservation],
                        fixed: dict[str, float]) -> set[str]:
    neighbours: dict[str, set[str]] = {}
    for o in observations:
        neighbours.setdefault(o.from_station, set()).add(o.to_station)
        neighbours.setdefault(o.to_station, set()).add(o.from_station)
    seen = set(fixed)
    stack = list(fixed)
    while stack:
        s = stack.pop()
        for nb in neighbours.get(s, ()):
            if nb not in seen:
                seen.add(nb)
                stack.append(nb)
    return seen


def adjust_level_net(observations: list[DiffObservation],
                     fixed: dict[str, float]) -> NetAdjustment:
    """Adjust a level network by weighted least squares.

    Args:
        observations: Elevation-difference observations.
        fixed: Datum -- mapping of station name to held elevation.
            Every free station must connect to the datum through the
            observation graph.

    Raises:
        ValueError: On empty input, non-positive sigma, a self-observation,
            an observation between two fixed stations, a disconnected
            network, or singular normal equations.
    """
    if not observations:
        raise ValueError("At least one observation is required")
    for o in observations:
        if o.sigma <= 0:
            raise ValueError(f"sigma must be positive (station {o.from_station})")
        if o.from_station == o.to_station:
            raise ValueError("Observation from a station to itself is meaningless")
    if not fixed:
        raise ValueError("At least one fixed station is required for the datum")

    fixed = dict(fixed)
    stations = set(fixed)
    for o in observations:
        stations.update((o.from_station, o.to_station))
    free = sorted(s for s in stations if s not in fixed)
    idx = {s: j for j, s in enumerate(free)}

    reachable = _reachable_stations(observations, fixed)
    stranded = [s for s in free if s not in reachable]
    if stranded:
        raise ValueError(f"Stations not connected to the datum: {stranded}")

    # Approximate elevations by propagating from the datum.
    approx = dict(fixed)
    changed = True
    while changed:
        changed = False
        for o in observations:
            if o.from_station in approx and o.to_station not in approx:
                approx[o.to_station] = approx[o.from_station] + o.delta_h
                changed = True
            elif o.to_station in approx and o.from_station not in approx:
                approx[o.from_station] = approx[o.to_station] - o.delta_h
                changed = True

    k, m = len(observations), len(free)
    a = zeros(k, m)
    ell: list[float] = [0.0] * k
    w = zeros(k, k)
    for r, o in enumerate(observations):
        a_fixed, b_fixed = o.from_station in fixed, o.to_station in fixed
        if a_fixed and b_fixed:
            raise ValueError(
                f"Observation {o.from_station}->{o.to_station} connects two "
                "fixed stations and carries no unknown"
            )
        ell[r] = o.delta_h - (approx[o.to_station] - approx[o.from_station])
        if not a_fixed:
            a[r][idx[o.from_station]] = -1.0
        if not b_fixed:
            a[r][idx[o.to_station]] = 1.0
        w[r][r] = 1.0 / (o.sigma ** 2)

    at = transpose(a)
    n = matmul(at, matmul(w, a))
    t = matvec(matmul(at, w), ell)
    try:
        qxx = inverse(n)
    except ValueError as exc:
        raise ValueError(
            "Normal equations are singular -- check the datum and network geometry"
        ) from exc
    x = matvec(qxx, t)
    v = [av - lv for av, lv in zip(matvec(a, x), ell)]

    dof = k - m
    sigma0 = None
    if dof > 0:
        s02 = sum(vi * w[i][i] * vi for i, vi in enumerate(v)) / dof
        sigma0 = math.sqrt(max(s02, 0.0))

    points = [
        AdjustedPoint(
            station=s,
            elevation=approx[s] + x[idx[s]],
            std_dev=(sigma0 * math.sqrt(qxx[idx[s]][idx[s]]) if sigma0 is not None else None),
        )
        for s in free
    ]
    points += [AdjustedPoint(station=s, elevation=e, std_dev=0.0)
               for s, e in sorted(fixed.items())]

    return NetAdjustment(
        points=points,
        residuals=v,
        adjusted_observations=[o.delta_h + vi for o, vi in zip(observations, v)],
        sigma0=sigma0,
        dof=dof,
    )
