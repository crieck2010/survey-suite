"""Unit tests for survey-geodesy. Run with: python -m unittest discover -s tests

UTM and geodesic reference values were cross-checked against pyproj 3.8
(EPSG:326xx/327xx and Geod.inv); the engine itself has no dependency on it.
"""
import math
import unittest

from geodesy import (
    ELLIPSOIDS,
    WGS84,
    HelmertParams,
    ecef_to_geodetic,
    geodesic_inverse,
    geodetic_to_ecef,
    helmert_3param,
    helmert_7param,
    latlon_to_utm,
    utm_to_latlon,
    utm_zone,
)


class TestEllipsoids(unittest.TestCase):
    def test_wgs84_derived(self):
        self.assertAlmostEqual(WGS84.b, 6356752.314245179, delta=1e-6)
        self.assertAlmostEqual(WGS84.e2, 0.00669437999014, places=11)

    def test_registry(self):
        self.assertIn("GRS80", ELLIPSOIDS)
        self.assertIn("Clarke1866", ELLIPSOIDS)
        self.assertEqual(ELLIPSOIDS["WGS84"].a, 6378137.0)


class TestConversions(unittest.TestCase):
    def test_equator_prime_meridian(self):
        x, y, z = geodetic_to_ecef(0.0, 0.0, 0.0)
        self.assertAlmostEqual(x, 6378137.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_north_pole(self):
        x, y, z = geodetic_to_ecef(90.0, 0.0, 0.0)
        self.assertAlmostEqual(x, 0.0, delta=1e-6)
        self.assertAlmostEqual(y, 0.0, delta=1e-6)
        self.assertAlmostEqual(z, 6356752.314245179, delta=1e-6)

    def test_roundtrip(self):
        lat, lon, h = 40.0, -75.0, 100.0
        x, y, z = geodetic_to_ecef(lat, lon, h)
        la2, lo2, h2 = ecef_to_geodetic(x, y, z)
        self.assertAlmostEqual(la2, lat, places=9)
        self.assertAlmostEqual(lo2, lon, places=9)
        self.assertAlmostEqual(h2, h, places=6)


class TestHelmert(unittest.TestCase):
    def test_identity(self):
        p = HelmertParams()
        self.assertEqual(helmert_7param(1.0, 2.0, 3.0, p), (1.0, 2.0, 3.0))

    def test_translation(self):
        self.assertEqual(helmert_3param(1.0, 2.0, 3.0, 10.0, 20.0, 30.0),
                         (11.0, 22.0, 33.0))

    def test_inverse_roundtrip(self):
        params = HelmertParams(dx=1.5, dy=-2.5, dz=3.5,
                               rx=0.5, ry=-0.25, rz=0.1, s_ppm=2.0)
        x, y, z = 4_200_000.0, -1_200_000.0, 4_700_000.0
        x2, y2, z2 = helmert_7param(x, y, z, params)
        x3, y3, z3 = helmert_7param(x2, y2, z2, params.inverse())
        # Negated parameters invert the linearised form; second-order
        # rotation terms leave a residual far below a millimetre.
        self.assertAlmostEqual(x3, x, delta=1e-4)
        self.assertAlmostEqual(y3, y, delta=1e-4)
        self.assertAlmostEqual(z3, z, delta=1e-4)


class TestUtm(unittest.TestCase):
    def test_zone(self):
        self.assertEqual(utm_zone(-75.0), 18)
        self.assertEqual(utm_zone(151.2093), 56)
        self.assertEqual(utm_zone(0.0), 31)
        self.assertEqual(utm_zone(139.6503), 54)

    def test_forward_central_meridian(self):
        # On the central meridian: easting is exactly the false easting.
        e, n, zone, hemi = latlon_to_utm(40.0, -75.0)
        self.assertEqual((zone, hemi), (18, "N"))
        self.assertAlmostEqual(e, 500000.0, places=6)
        self.assertAlmostEqual(n, 4427757.219, delta=0.005)

    def test_forward_southern_hemisphere(self):
        e, n, zone, hemi = latlon_to_utm(-33.8688, 151.2093)
        self.assertEqual((zone, hemi), (56, "S"))
        self.assertAlmostEqual(e, 334368.634, delta=0.005)
        self.assertAlmostEqual(n, 6250948.345, delta=0.005)

    def test_forward_greenwich(self):
        e, n, zone, hemi = latlon_to_utm(51.4778, -0.0015)
        self.assertEqual((zone, hemi), (30, "N"))
        self.assertAlmostEqual(e, 708213.951, delta=0.005)
        self.assertAlmostEqual(n, 5707224.543, delta=0.005)

    def test_inverse_roundtrip(self):
        for lat, lon in [(40.0, -75.0), (-33.8688, 151.2093),
                         (51.4778, -0.0015), (70.0, 20.0)]:
            e, n, zone, hemi = latlon_to_utm(lat, lon)
            la2, lo2 = utm_to_latlon(e, n, zone, hemi)
            # Series truncation limits the inverse to a few millimetres.
            self.assertAlmostEqual(la2, lat, places=7)
            self.assertAlmostEqual(lo2, lon, places=7)

    def test_bad_hemisphere_raises(self):
        with self.assertRaises(ValueError):
            utm_to_latlon(500000, 4400000, 18, "X")


class TestVincenty(unittest.TestCase):
    def test_known_distance_and_azimuths(self):
        d, az12, az21 = geodesic_inverse(40.0, -75.0, 41.0, -74.0)
        self.assertAlmostEqual(d, 139698.755, places=3)
        self.assertAlmostEqual(az12, 37.0333, places=4)
        self.assertAlmostEqual(az21, 217.6828, places=4)

    def test_equatorial_degree(self):
        d, az12, az21 = geodesic_inverse(0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(d, 111319.491, places=3)
        self.assertAlmostEqual(az12, 90.0, places=6)
        self.assertAlmostEqual(az21, 270.0, places=6)

    def test_long_line(self):
        d, az12, az21 = geodesic_inverse(-33.8688, 151.2093, 35.6762, 139.6503)
        self.assertAlmostEqual(d, 7792174.827, places=3)
        self.assertAlmostEqual(az12, 349.9975, places=4)
        self.assertAlmostEqual(az21, 169.7747, places=4)

    def test_coincident_points(self):
        d, az12, az21 = geodesic_inverse(40.0, -75.0, 40.0, -75.0)
        self.assertEqual(d, 0.0)

    def test_antipodal_raises(self):
        with self.assertRaises(ValueError):
            geodesic_inverse(0.0, 0.0, 0.0, 180.0)


if __name__ == "__main__":
    unittest.main()
