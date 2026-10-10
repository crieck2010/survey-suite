"""Unit tests for survey-cogo. Run with: python -m unittest discover -s tests"""
import math
import unittest

from cogo import (
    Leg,
    Point,
    angular_misclosure,
    azimuth_to_bearing,
    azimuths_from_turned_angles,
    bearing_bearing,
    bearing_to_azimuth,
    compass_adjust,
    decimal_to_dms,
    distance_distance,
    dms_to_decimal,
    format_dms,
    forward,
    inverse,
    linear_misclosure,
    normalize_angle,
    parse_dms,
    polygon_area,
    polygon_perimeter,
    relative_precision,
    run_traverse,
)


class TestAngles(unittest.TestCase):
    def test_dms_to_decimal(self):
        self.assertAlmostEqual(dms_to_decimal(122, 30, 15), 122.5041666667, places=7)
        self.assertAlmostEqual(dms_to_decimal(45, 30), 45.5)
        self.assertAlmostEqual(dms_to_decimal(-30, 15), -30.25)

    def test_parse_dms(self):
        self.assertAlmostEqual(parse_dms("122°30'15\""), 122.5041666667, places=7)
        self.assertAlmostEqual(parse_dms("45°30'"), 45.5)
        self.assertAlmostEqual(parse_dms("-10°00'36\""), -10.01)
        with self.assertRaises(ValueError):
            parse_dms("not an angle")

    def test_decimal_to_dms_roundtrip(self):
        d, m, s = decimal_to_dms(122.5041666667)
        self.assertEqual((d, m), (122, 30))
        self.assertAlmostEqual(s, 15.0, places=4)

    def test_format_dms(self):
        self.assertEqual(format_dms(45.5), "45°30'00.0\"")

    def test_normalize_angle(self):
        self.assertAlmostEqual(normalize_angle(370), 10)
        self.assertAlmostEqual(normalize_angle(-10), 350)
        self.assertAlmostEqual(normalize_angle(720), 0)

    def test_azimuth_to_bearing(self):
        self.assertEqual(azimuth_to_bearing(45), "N 45°00'00.0\" E")
        self.assertEqual(azimuth_to_bearing(135), "S 45°00'00.0\" E")
        self.assertEqual(azimuth_to_bearing(225), "S 45°00'00.0\" W")
        self.assertEqual(azimuth_to_bearing(315), "N 45°00'00.0\" W")

    def test_bearing_to_azimuth(self):
        self.assertAlmostEqual(bearing_to_azimuth("N 45°00'00\" E"), 45)
        self.assertAlmostEqual(bearing_to_azimuth("S 30°00'00\" W"), 210)
        self.assertAlmostEqual(bearing_to_azimuth("S 10°00'00\" E"), 170)
        self.assertAlmostEqual(bearing_to_azimuth("N 10°00'00\" W"), 350)
        with self.assertRaises(ValueError):
            bearing_to_azimuth("bogus")

    def test_bearing_roundtrip(self):
        for az in (0, 12.5, 90, 137.25, 200, 270, 359.9):
            self.assertAlmostEqual(
                bearing_to_azimuth(azimuth_to_bearing(az)), az % 360, places=6)


class TestInverseForward(unittest.TestCase):
    def test_inverse_cardinal(self):
        inv = inverse(Point(0, 0), Point(50, 0))
        self.assertAlmostEqual(inv.azimuth, 0)
        self.assertAlmostEqual(inv.distance, 50)
        inv = inverse(Point(0, 0), Point(0, -50))
        self.assertAlmostEqual(inv.azimuth, 270)

    def test_inverse_diagonal(self):
        inv = inverse(Point(0, 0), Point(100, 100))
        self.assertAlmostEqual(inv.azimuth, 45)
        self.assertAlmostEqual(inv.distance, math.hypot(100, 100))

    def test_inverse_coincident_raises(self):
        with self.assertRaises(ValueError):
            inverse(Point(1, 1), Point(1, 1))

    def test_forward(self):
        p = forward(Point(0, 0), 90, 100)
        self.assertAlmostEqual(p.northing, 0, places=9)
        self.assertAlmostEqual(p.easting, 100, places=9)

    def test_forward_inverse_roundtrip(self):
        start = Point(1000, 2000)
        p = forward(start, 123.456, 250.5)
        inv = inverse(start, p)
        self.assertAlmostEqual(inv.azimuth, 123.456, places=9)
        self.assertAlmostEqual(inv.distance, 250.5, places=9)


class TestIntersections(unittest.TestCase):
    def test_bearing_bearing(self):
        p = bearing_bearing(Point(0, 0), 45, Point(0, 100), 315)
        self.assertAlmostEqual(p.northing, 50, places=9)
        self.assertAlmostEqual(p.easting, 50, places=9)

    def test_bearing_bearing_parallel_raises(self):
        with self.assertRaises(ValueError):
            bearing_bearing(Point(0, 0), 90, Point(0, 100), 90)

    def test_distance_distance(self):
        a, b = distance_distance(Point(0, 0), 3, Point(0, 4), 5)
        got = sorted([(round(p.northing, 9), round(p.easting, 9)) for p in (a, b)])
        self.assertEqual(got, [(-3.0, 0.0), (3.0, 0.0)])

    def test_distance_distance_separate_raises(self):
        with self.assertRaises(ValueError):
            distance_distance(Point(0, 0), 1, Point(0, 100), 1)

    def test_distance_distance_concentric_raises(self):
        with self.assertRaises(ValueError):
            distance_distance(Point(0, 0), 1, Point(0, 0), 2)


class TestTraverse(unittest.TestCase):
    def square_legs(self):
        return [Leg(0, 100), Leg(90, 100), Leg(180, 100), Leg(270, 100)]

    def test_run_traverse_closes(self):
        pts = run_traverse(Point(0, 0), self.square_legs())
        self.assertEqual(len(pts), 5)
        self.assertAlmostEqual(pts[-1].northing, 0, places=9)
        self.assertAlmostEqual(pts[-1].easting, 0, places=9)

    def test_azimuths_from_turned_angles(self):
        az = azimuths_from_turned_angles(90, [90, 90, 90], turn="right")
        self.assertEqual([round(a) for a in az], [90, 0, 270, 180])

    def test_azimuths_from_turned_angles_bad_turn(self):
        with self.assertRaises(ValueError):
            azimuths_from_turned_angles(0, [90], turn="up")

    def test_angular_misclosure(self):
        self.assertAlmostEqual(angular_misclosure([90, 90, 90, 90], 4), 0)
        self.assertAlmostEqual(angular_misclosure([90, 90, 90, 91], 4), 1)

    def test_linear_misclosure_and_precision(self):
        mis = linear_misclosure(Point(0, 0), Point(0.05, -0.03))
        self.assertAlmostEqual(mis.linear_error, math.hypot(0.05, 0.03))
        ratio, text = relative_precision(mis.linear_error, 400)
        self.assertAlmostEqual(ratio, 400 / mis.linear_error)
        self.assertTrue(text.startswith("1:"))

    def test_compass_adjust_closes(self):
        legs = [Leg(0, 100), Leg(90, 100), Leg(180, 100), Leg(269, 100)]
        raw = run_traverse(Point(0, 0), legs)
        mis = linear_misclosure(Point(0, 0), raw[-1])
        self.assertGreater(mis.linear_error, 1.0)  # sanity: it really miscloses
        adj = compass_adjust(Point(0, 0), legs)
        self.assertAlmostEqual(adj[-1].northing, 0, places=9)
        self.assertAlmostEqual(adj[-1].easting, 0, places=9)


class TestArea(unittest.TestCase):
    def test_polygon_area_square(self):
        pts = [Point(0, 0), Point(0, 100), Point(100, 100), Point(100, 0)]
        self.assertAlmostEqual(polygon_area(pts), 10000)

    def test_polygon_area_triangle(self):
        pts = [Point(0, 0), Point(0, 4), Point(3, 0)]
        self.assertAlmostEqual(polygon_area(pts), 6)

    def test_polygon_area_needs_3_points(self):
        with self.assertRaises(ValueError):
            polygon_area([Point(0, 0), Point(1, 1)])

    def test_polygon_perimeter(self):
        pts = [Point(0, 0), Point(0, 100), Point(100, 100), Point(100, 0)]
        self.assertAlmostEqual(polygon_perimeter(pts), 400)


if __name__ == "__main__":
    unittest.main()
