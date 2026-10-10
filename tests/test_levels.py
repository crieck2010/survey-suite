"""Unit tests for survey-levels. Run with: python -m unittest discover -s tests"""
import unittest

from levels import (
    Setup,
    adjust_loop,
    allowable_misclosure,
    loop_misclosure,
    page_check,
    passes,
    reduce_levels,
)


def example_setups():
    # BM_A @ 100.000. Loop miscloses by -5 mm.
    return [
        Setup(backsight_station="BM_A", backsight=1.500,
              foresight_station="TP1", foresight=0.800,
              sideshots=(("SS1", 1.000),)),
        Setup(backsight_station="TP1", backsight=1.200,
              foresight_station="BM_A", foresight=1.905),
    ]


class TestReduction(unittest.TestCase):
    def test_reduce_levels(self):
        pts = reduce_levels("BM_A", 100.000, example_setups())
        by_station = {p.station: p for p in pts if p.role != "sideshot"}
        self.assertAlmostEqual(by_station["TP1"].elevation, 100.700, places=9)
        # Closing shot on BM_A
        closers = [p for p in pts if p.station == "BM_A" and p.role == "turning_point"]
        self.assertEqual(len(closers), 1)
        self.assertAlmostEqual(closers[0].elevation, 99.995, places=9)

    def test_sideshot(self):
        pts = reduce_levels("BM_A", 100.000, example_setups())
        ss = [p for p in pts if p.station == "SS1"]
        self.assertEqual(len(ss), 1)
        self.assertEqual(ss[0].role, "sideshot")
        self.assertAlmostEqual(ss[0].elevation, 100.500, places=9)

    def test_setup_index_tags(self):
        pts = reduce_levels("BM_A", 100.000, example_setups())
        self.assertEqual(pts[0].setup_index, 0)  # starting benchmark
        tp1 = next(p for p in pts if p.station == "TP1")
        self.assertEqual(tp1.setup_index, 1)

    def test_unknown_backsight_raises(self):
        bad = [Setup("NOPE", 1.0, "TP1", 0.5)]
        with self.assertRaises(ValueError):
            reduce_levels("BM_A", 100.000, bad)

    def test_page_check_ok(self):
        setups = example_setups()
        pts = reduce_levels("BM_A", 100.000, setups)
        closing = [p for p in pts if p.station == "BM_A" and p.role == "turning_point"][0]
        chk = page_check(setups, 100.000, closing.elevation)
        self.assertAlmostEqual(chk.bs_sum, 2.700, places=9)
        self.assertAlmostEqual(chk.fs_sum, 2.705, places=9)
        self.assertAlmostEqual(chk.check, -0.005, places=9)
        self.assertTrue(chk.ok)

    def test_page_check_detects_tampering(self):
        setups = example_setups()
        chk = page_check(setups, 100.000, 100.010)  # wrong end elevation
        self.assertFalse(chk.ok)


class TestAdjustment(unittest.TestCase):
    def test_loop_misclosure(self):
        self.assertAlmostEqual(loop_misclosure(100.000, 99.995), -0.005, places=9)

    def test_allowable_misclosure(self):
        self.assertAlmostEqual(allowable_misclosure(1.0, "third_order"), 12.0)
        self.assertAlmostEqual(allowable_misclosure(4.0, "third_order"), 24.0)
        self.assertAlmostEqual(allowable_misclosure(1.0, "first_order"), 4.0)
        self.assertAlmostEqual(allowable_misclosure(2.25, 10.0), 15.0)

    def test_allowable_bad_spec_raises(self):
        with self.assertRaises(ValueError):
            allowable_misclosure(1.0, "fourth_order")

    def test_allowable_negative_distance_raises(self):
        with self.assertRaises(ValueError):
            allowable_misclosure(-1.0)

    def test_passes(self):
        self.assertTrue(passes(5.0, 12.0))
        self.assertTrue(passes(-12.0, 12.0))
        self.assertFalse(passes(12.1, 12.0))

    def test_adjust_loop_closes(self):
        setups = example_setups()
        pts = reduce_levels("BM_A", 100.000, setups)
        closing_elev = next(p.elevation for p in pts
                            if p.station == "BM_A" and p.role == "turning_point")
        mis = loop_misclosure(100.000, closing_elev)
        adj = adjust_loop(pts, mis, n_setups=2)
        closing = [p for p in adj if p.station == "BM_A" and p.role == "turning_point"][0]
        self.assertAlmostEqual(closing.elevation, 100.000, places=9)
        tp1 = next(p for p in adj if p.station == "TP1")
        self.assertAlmostEqual(tp1.elevation, 100.7025, places=9)
        start = adj[0]
        self.assertAlmostEqual(start.elevation, 100.000, places=9)

    def test_adjust_loop_bad_n_setups(self):
        pts = reduce_levels("BM_A", 100.000, example_setups())
        with self.assertRaises(ValueError):
            adjust_loop(pts, -0.005, 0)


if __name__ == "__main__":
    unittest.main()
