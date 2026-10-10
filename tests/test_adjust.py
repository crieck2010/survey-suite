"""Unit tests for survey-adjust. Run with: python -m unittest discover -s tests"""
import math
import unittest

from adjust import (
    DiffObservation,
    adjust_angles,
    adjust_level_net,
    chi_square_critical,
    global_test,
    inverse,
    matmul,
    solve,
    transpose,
)


def example_net():
    # A fixed at 100.000; B and C free. Third leg over-observes A->C.
    return (
        [
            DiffObservation("A", "B", 1.000, sigma=1.0),
            DiffObservation("B", "C", 2.000, sigma=1.0),
            DiffObservation("A", "C", 3.010, sigma=1.0),
        ],
        {"A": 100.000},
    )


class TestMatrices(unittest.TestCase):
    def test_matmul(self):
        self.assertEqual(matmul([[1, 2], [3, 4]], [[5, 6], [7, 8]]),
                         [[19, 22], [43, 50]])

    def test_transpose(self):
        self.assertEqual(transpose([[1, 2, 3], [4, 5, 6]]),
                         [[1, 4], [2, 5], [3, 6]])

    def test_inverse(self):
        inv = inverse([[4, 7], [2, 6]])
        for row_got, row_exp in zip(inv, [[0.6, -0.7], [-0.2, 0.4]]):
            for got, exp in zip(row_got, row_exp):
                self.assertAlmostEqual(got, exp, places=9)

    def test_inverse_singular_raises(self):
        with self.assertRaises(ValueError):
            inverse([[1, 2], [2, 4]])

    def test_solve(self):
        x = solve([[2, 1], [1, 2]], [3, 3])
        self.assertAlmostEqual(x[0], 1.0, places=9)
        self.assertAlmostEqual(x[1], 1.0, places=9)


class TestLevelNet(unittest.TestCase):
    def test_adjusted_elevations(self):
        obs, fixed = example_net()
        res = adjust_level_net(obs, fixed)
        elev = {p.station: p.elevation for p in res.points}
        self.assertAlmostEqual(elev["B"], 101.0033333, places=6)
        self.assertAlmostEqual(elev["C"], 103.0066667, places=6)
        self.assertAlmostEqual(elev["A"], 100.0, places=9)  # datum held

    def test_residuals(self):
        obs, fixed = example_net()
        res = adjust_level_net(obs, fixed)
        for got, exp in zip(res.residuals, [1/300, 1/300, -1/300]):
            self.assertAlmostEqual(got, exp, places=9)
        # Adjusted observations honour the adjusted elevations
        self.assertAlmostEqual(
            res.adjusted_observations[0] + 100.0,
            next(p.elevation for p in res.points if p.station == "B"), places=9)

    def test_statistics(self):
        obs, fixed = example_net()
        res = adjust_level_net(obs, fixed)
        self.assertEqual(res.dof, 1)
        self.assertAlmostEqual(res.sigma0, math.sqrt(1/30000), places=9)
        stds = {p.station: p.std_dev for p in res.points}
        self.assertAlmostEqual(stds["B"], math.sqrt(1/30000) * math.sqrt(2/3), places=9)
        self.assertAlmostEqual(stds["C"], math.sqrt(1/30000) * math.sqrt(2/3), places=9)
        self.assertEqual(stds["A"], 0.0)

    def test_zero_redundancy(self):
        res = adjust_level_net([DiffObservation("A", "B", 1.0)], {"A": 100.0})
        self.assertEqual(res.dof, 0)
        self.assertIsNone(res.sigma0)
        b = next(p for p in res.points if p.station == "B")
        self.assertAlmostEqual(b.elevation, 101.0, places=9)
        self.assertIsNone(b.std_dev)

    def test_disconnected_network_raises(self):
        with self.assertRaises(ValueError):
            adjust_level_net([DiffObservation("B", "C", 1.0)], {"A": 100.0})

    def test_fixed_to_fixed_observation_raises(self):
        with self.assertRaises(ValueError):
            adjust_level_net([DiffObservation("A", "B", 1.0)],
                             {"A": 100.0, "B": 101.0})

    def test_no_datum_raises(self):
        with self.assertRaises(ValueError):
            adjust_level_net([DiffObservation("A", "B", 1.0)], {})

    def test_bad_sigma_raises(self):
        with self.assertRaises(ValueError):
            adjust_level_net([DiffObservation("A", "B", 1.0, sigma=0.0)],
                             {"A": 100.0})

    def test_weighted_observation(self):
        # A precise A->C leg (sigma 0.1) pulls C toward the direct observation.
        obs = [
            DiffObservation("A", "B", 1.000, sigma=1.0),
            DiffObservation("B", "C", 2.000, sigma=1.0),
            DiffObservation("A", "C", 3.010, sigma=0.1),
        ]
        res = adjust_level_net(obs, {"A": 100.000})
        elev = {p.station: p.elevation for p in res.points}
        # C should sit much closer to 103.010 than in the equal-weight case
        self.assertGreater(elev["C"], 103.009)


class TestConditionAngles(unittest.TestCase):
    def test_equal_weights(self):
        adj, corr = adjust_angles([90, 90, 90, 91])
        self.assertAlmostEqual(sum(adj), 360.0, places=9)
        for c in corr:
            self.assertAlmostEqual(c, -0.25, places=9)
        self.assertAlmostEqual(adj[3], 90.75, places=9)

    def test_weighted(self):
        adj, corr = adjust_angles([90, 90, 90, 91], weights=[1, 1, 1, 4])
        self.assertAlmostEqual(sum(adj), 360.0, places=9)
        self.assertAlmostEqual(corr[0], -1/3.25, places=9)
        self.assertAlmostEqual(corr[3], -0.25/3.25, places=9)

    def test_already_closed(self):
        adj, corr = adjust_angles([90, 90, 90, 90])
        self.assertTrue(all(abs(c) < 1e-12 for c in corr))

    def test_bad_weights_raise(self):
        with self.assertRaises(ValueError):
            adjust_angles([90, 90], weights=[1])
        with self.assertRaises(ValueError):
            adjust_angles([90, 90], weights=[1, 0])


class TestStats(unittest.TestCase):
    def test_chi_square_critical(self):
        # True value for dof=1, alpha=0.05 is 3.841; approximation is close.
        self.assertAlmostEqual(chi_square_critical(1, 0.05), 3.841, delta=0.15)
        with self.assertRaises(ValueError):
            chi_square_critical(0)
        with self.assertRaises(ValueError):
            chi_square_critical(5, alpha=0.07)

    def test_global_test_passes(self):
        passed, stat, crit = global_test(1, 1/30000)
        self.assertTrue(passed)
        self.assertAlmostEqual(stat, 1/30000, places=9)

    def test_global_test_fails(self):
        passed, stat, crit = global_test(1, 100.0)
        self.assertFalse(passed)
        self.assertAlmostEqual(stat, 100.0)


if __name__ == "__main__":
    unittest.main()
