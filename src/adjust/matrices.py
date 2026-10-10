"""Minimal pure-Python matrix toolkit for least-squares adjustment.

Kept deliberately small: just enough to form and solve normal equations
for teaching- and project-size networks. For large production networks,
swap this module for numpy/scipy -- the public API of the adjustment
functions does not depend on these internals.
"""
from __future__ import annotations

Matrix = list[list[float]]
Vector = list[float]

_EPS = 1e-12


def zeros(rows: int, cols: int) -> Matrix:
    return [[0.0] * cols for _ in range(rows)]


def identity(n: int) -> Matrix:
    m = zeros(n, n)
    for i in range(n):
        m[i][i] = 1.0
    return m


def transpose(a: Matrix) -> Matrix:
    return [list(row) for row in zip(*a)]


def matmul(a: Matrix, b: Matrix) -> Matrix:
    n, p, m = len(a), len(a[0]), len(b[0])
    if len(b) != p:
        raise ValueError("Incompatible matrix dimensions")
    out = zeros(n, m)
    for i in range(n):
        for k in range(p):
            aik = a[i][k]
            if aik != 0.0:
                for j in range(m):
                    out[i][j] += aik * b[k][j]
    return out


def matvec(a: Matrix, x: Vector) -> Vector:
    if len(a[0]) != len(x):
        raise ValueError("Incompatible dimensions")
    return [sum(row[j] * x[j] for j in range(len(x))) for row in a]


def inverse(a: Matrix) -> Matrix:
    """Matrix inverse by Gauss-Jordan elimination with partial pivoting.

    Raises ValueError if the matrix is singular.
    """
    n = len(a)
    if any(len(row) != n for row in a):
        raise ValueError("Only square matrices can be inverted")
    # Augment with the identity and eliminate.
    m = [list(map(float, row)) + [1.0 if i == j else 0.0 for j in range(n)]
         for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < _EPS:
            raise ValueError("Matrix is singular")
        m[col], m[pivot] = m[pivot], m[col]
        piv = m[col][col]
        m[col] = [v / piv for v in m[col]]
        for r in range(n):
            if r != col and m[r][col] != 0.0:
                factor = m[r][col]
                m[r] = [rv - factor * cv for rv, cv in zip(m[r], m[col])]
    return [row[n:] for row in m]


def solve(a: Matrix, b: Vector) -> Vector:
    """Solve the linear system A x = b."""
    return matvec(inverse(a), b)
