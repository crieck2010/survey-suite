"""Unit tests for survey-suite. Run with: python -m unittest discover -s tests"""
import os
import unittest


def make_gga(lat_nmea, lon_nmea, hemi_lat="N", hemi_lon="W", alt="545.4"):
    body = (f"GPGGA,123519,{lat_nmea},{hemi_lat},{lon_nmea},{hemi_lon},"
            f"4,08,0.9,{alt},M,46.9,M,,")
    c = 0
    for ch in body:
        c ^= ord(ch)
    return f"${body}*{c:02X}"


class TestDemVolumeWorkflow(unittest.TestCase):
    def test_flat_ground(self):
        from suite.workflows import dem_volume_workflow
        pts = [(float(x), float(y), 1.0)
               for x in range(10) for y in range(10)]
        pts.append((4.5, 4.5, 9.0))  # roof: classified, not ground
        r = dem_volume_workflow(pts, 0, 0, 1.0, 10, 10, 0.0)
        self.assertEqual(r["ground_count"], 100)
        self.assertAlmostEqual(r["cut"], 100.0, places=9)
        self.assertAlmostEqual(r["fill"], 0.0, places=9)
        self.assertAlmostEqual(r["net"], 100.0, places=9)
        self.assertEqual(r["dtm"].height, 10)
        self.assertEqual(r["dtm"].width, 10)


class TestLevelToAdjustmentWorkflow(unittest.TestCase):
    def test_closed_loop(self):
        from levels import Setup
        from suite.workflows import level_to_adjustment_workflow
        setups = [
            Setup("BM-A", 1.5, "TP1", 1.0),
            Setup("TP1", 1.2, "TP2", 1.7),
            Setup("TP2", 1.1, "BM-A", 1.1),
        ]
        r = level_to_adjustment_workflow("BM-A", 100.0, setups)
        self.assertTrue(r["page_check"].ok)
        self.assertEqual(len(r["points"]), 4)
        adj = r["adjustment"]
        elev = {p.station: p.elevation for p in adj.points}
        self.assertAlmostEqual(elev["TP1"], 100.5, places=9)
        self.assertAlmostEqual(elev["TP2"], 100.0, places=9)
        self.assertAlmostEqual(elev["BM-A"], 100.0, places=9)


class TestGnssCogoControlWorkflow(unittest.TestCase):
    def test_control_point(self):
        from suite.workflows import gnss_cogo_control_workflow
        lines = [make_gga(f"4309.39{i}", "07736.528") for i in range(6, 9)]
        r = gnss_cogo_control_workflow(lines, "CTRL-1")
        self.assertEqual(r["n_fixes"], 3)
        self.assertAlmostEqual(r["mean_lat"], 43 + 9.397 / 60, places=9)
        self.assertAlmostEqual(r["mean_lon"], -(77 + 36.528 / 60), places=9)
        self.assertEqual(r["zone"], 18)
        self.assertEqual(r["hemisphere"], "N")
        cp = r["control_point"]
        self.assertEqual(cp.name, "CTRL-1")
        self.assertGreater(cp.easting, 200000)
        self.assertGreater(r["accuracy_m"], 0)

    def test_no_fixes_raises(self):
        from suite.workflows import gnss_cogo_control_workflow
        with self.assertRaises(ValueError):
            gnss_cogo_control_workflow(["$GPGGA,bad*00", "hello"])


class TestLicensingStub(unittest.TestCase):
    def test_no_key(self):
        from suite.licensing import check_license
        env = os.environ.pop("SURVEY_SUITE_LICENSE", None)
        try:
            st = check_license()
            self.assertFalse(st.valid)
            self.assertEqual(st.tier, "none")
        finally:
            if env is not None:
                os.environ["SURVEY_SUITE_LICENSE"] = env

    def test_stub_key_accepted(self):
        from suite.licensing import check_license
        os.environ["SURVEY_SUITE_LICENSE"] = "beta-test-key-123"
        try:
            st = check_license()
            self.assertTrue(st.valid)
        finally:
            del os.environ["SURVEY_SUITE_LICENSE"]

    def test_never_raises(self):
        from suite import licensing
        self.assertFalse(licensing.license_required())


class TestUpdatesStub(unittest.TestCase):
    def test_unreachable(self):
        from suite.updates import check_for_updates
        ok, latest = check_for_updates("0.1.0",
                                       url="http://127.0.0.1:9/version.txt")
        self.assertFalse(ok)
        self.assertIsNone(latest)


class TestApp(unittest.TestCase):
    def test_imports_without_display(self):
        import suite.app as app
        self.assertTrue(callable(app.main))
        self.assertTrue(callable(app.build_app))

    def test_parse_grid(self):
        from suite.app import parse_grid
        self.assertEqual(parse_grid("1,2;3,4"),
                         [[1.0, 2.0], [3.0, 4.0]])
        with self.assertRaises(ValueError):
            parse_grid("1,2;3")


if __name__ == "__main__":
    unittest.main()
