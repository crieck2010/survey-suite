"""Unit tests for survey-gnss. Run with: python -m unittest discover -s tests"""
import math
import unittest

from gnss import (
    Fix,
    Session,
    assess_quality,
    baseline,
    checksum_ok,
    dop_from_unit_vectors,
    dop_quality,
    ecef_to_geodetic,
    geodetic_to_ecef,
    iter_sentences,
    nmea_date_to_tuple,
    nmea_time_to_tuple,
    nmea_to_decimal,
    parse_gsa,
    parse_gsv,
    parse_gga,
    parse_rmc,
    parse_sentence,
    parse_vtg,
    sentence_type,
    unit_vectors_to_enu,
)

GGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
RMC = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
GSA = "$GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1*39"
GSV = ("$GPGSV,2,1,08,01,40,083,46,02,17,308,41,"
       "03,12,220,44,04,55,150,47*77")
VTG = "$GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48"


class TestChecksum(unittest.TestCase):
    def test_valid(self):
        for s in (GGA, RMC, GSA, GSV, VTG):
            self.assertTrue(checksum_ok(s), s[:12])

    def test_corrupted(self):
        bad = GGA[:-2] + "00"
        self.assertFalse(checksum_ok(bad))

    def test_malformed(self):
        self.assertFalse(checksum_ok("GPGGA,123519*47"))
        self.assertFalse(checksum_ok("$GPGGA,123519*ZZ"))

    def test_sentence_type(self):
        self.assertEqual(sentence_type(GGA), "GGA")
        self.assertEqual(sentence_type("$GLGSA,A,3,,,,,,,,,,,,,,,*00")[:3], "GSA")


class TestNmeaFields(unittest.TestCase):
    def test_lat_lon(self):
        self.assertAlmostEqual(nmea_to_decimal("4807.038", "N"),
                               48 + 7.038 / 60, places=9)
        self.assertAlmostEqual(nmea_to_decimal("01131.000", "E"),
                               11 + 31.0 / 60, places=9)
        self.assertAlmostEqual(nmea_to_decimal("4807.038", "S"),
                               -(48 + 7.038 / 60), places=9)
        self.assertAlmostEqual(nmea_to_decimal("01131.000", "W"),
                               -(11 + 31.0 / 60), places=9)

    def test_lat_lon_empty(self):
        self.assertIsNone(nmea_to_decimal("", "N"))
        self.assertIsNone(nmea_to_decimal("4807.038", ""))

    def test_time(self):
        self.assertEqual(nmea_time_to_tuple("123519"), (12, 35, 19.0))
        self.assertEqual(nmea_time_to_tuple("123519.50"), (12, 35, 19.5))
        self.assertIsNone(nmea_time_to_tuple(""))

    def test_date(self):
        self.assertEqual(nmea_date_to_tuple("230394"), (1994, 3, 23))
        self.assertEqual(nmea_date_to_tuple("010203"), (2003, 2, 1))
        self.assertIsNone(nmea_date_to_tuple(""))


class TestParsers(unittest.TestCase):
    def test_gga(self):
        g = parse_gga(GGA)
        self.assertEqual(g.time, (12, 35, 19.0))
        self.assertAlmostEqual(g.lat, 48 + 7.038 / 60, places=9)
        self.assertAlmostEqual(g.lon, 11 + 31.0 / 60, places=9)
        self.assertEqual(g.quality, 1)
        self.assertEqual(g.num_sats, 8)
        self.assertAlmostEqual(g.hdop, 0.9)
        self.assertAlmostEqual(g.altitude, 545.4)
        self.assertAlmostEqual(g.geoid_sep, 46.9)

    def test_rmc(self):
        r = parse_rmc(RMC)
        self.assertEqual(r.status, "A")
        self.assertAlmostEqual(r.lat, 48 + 7.038 / 60, places=9)
        self.assertAlmostEqual(r.course_deg, 84.4)
        self.assertAlmostEqual(r.speed_knots, 22.4)
        self.assertEqual(r.date, (1994, 3, 23))

    def test_gsa(self):
        g = parse_gsa(GSA)
        self.assertEqual(g.fix_type, 3)
        self.assertEqual(g.sats_used, (4, 5, 9, 12, 24))
        self.assertAlmostEqual(g.pdop, 2.5)
        self.assertAlmostEqual(g.hdop, 1.3)
        self.assertAlmostEqual(g.vdop, 2.1)

    def test_gsv(self):
        g = parse_gsv(GSV)
        self.assertEqual(g.total_sats, 8)
        self.assertEqual(len(g.satellites), 4)
        s = g.satellites[0]
        self.assertEqual((s.prn, s.elevation_deg, s.azimuth_deg, s.snr_dbhz),
                         (1, 40.0, 83.0, 46.0))

    def test_vtg(self):
        v = parse_vtg(VTG)
        self.assertAlmostEqual(v.course_true, 54.7)
        self.assertAlmostEqual(v.speed_knots, 5.5)
        self.assertAlmostEqual(v.speed_kmh, 10.2)

    def test_dispatcher(self):
        self.assertEqual(parse_sentence(GGA).quality, 1)
        self.assertEqual(parse_sentence(RMC).status, "A")
        self.assertEqual(parse_sentence(GSA).fix_type, 3)
        self.assertEqual(len(parse_sentence(GSV).satellites), 4)
        self.assertAlmostEqual(parse_sentence(VTG).speed_kmh, 10.2)

    def test_dispatcher_unknown(self):
        body = "GPXYZ,1,2,3"
        c = 0
        for ch in body:
            c ^= ord(ch)
        s = "$" + body + "*" + format(c, "02X")
        self.assertIsNone(parse_sentence(s))

    def test_dispatcher_bad_checksum_raises(self):
        with self.assertRaises(ValueError):
            parse_sentence(GGA[:-2] + "00")

    def test_iter_sentences(self):
        lines = [GGA, "$GPGGA,bad*00", RMC, "not a sentence", GSA]
        parsed = list(iter_sentences(lines))
        self.assertEqual(len(parsed), 3)
        self.assertEqual([sentence_type(GGA), sentence_type(RMC),
                          sentence_type(GSA)],
                         ["GGA", "RMC", "GSA"])

    def test_iter_sentences_strict(self):
        with self.assertRaises(ValueError):
            list(iter_sentences([GGA[:-2] + "00"], skip_bad=False))


class TestCoords(unittest.TestCase):
    def test_ecef_roundtrip(self):
        for lat, lon, h in [(48.1173, 11.5167, 545.4),
                            (-33.8688, 151.2093, 58.0),
                            (0.0, 0.0, 0.0)]:
            x, y, z = geodetic_to_ecef(lat, lon, h)
            la2, lo2, h2 = ecef_to_geodetic(x, y, z)
            self.assertAlmostEqual(la2, lat, places=9)
            self.assertAlmostEqual(lo2, lon, places=9)
            self.assertAlmostEqual(h2, h, places=3)

    def test_ecef_known_value(self):
        # Equator/prime meridian at h=0 -> x = a, y = z = 0.
        x, y, z = geodetic_to_ecef(0.0, 0.0, 0.0)
        self.assertAlmostEqual(x, 6378137.0, places=3)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_baseline(self):
        p1 = geodetic_to_ecef(48.0, 11.0, 500.0)
        p2 = geodetic_to_ecef(48.0, 11.0, 510.0)
        d, length = baseline(p1, p2)
        self.assertAlmostEqual(length, 10.0, places=6)
        self.assertAlmostEqual(math.sqrt(sum(c * c for c in d)), 10.0,
                               places=9)

    def test_unit_vectors_to_enu_zenith(self):
        # At lat=0, lon=0 the up direction is +x in ECEF.
        e, n, u = unit_vectors_to_enu(0.0, 0.0, [(1.0, 0.0, 0.0)])[0]
        self.assertAlmostEqual(e, 0.0, places=12)
        self.assertAlmostEqual(n, 0.0, places=12)
        self.assertAlmostEqual(u, 1.0, places=12)


class TestDop(unittest.TestCase):
    # Hand-computed: unit vectors (0,0,1),(1,0,0),(0,1,0),(-1,0,0).
    # N = A^T A has inverse diag block giving
    # qe=0.5, qn=1.5, qu=1.5, qt=0.5.
    VECTORS = [(0, 0, 1), (1, 0, 0), (0, 1, 0), (-1, 0, 0)]

    def test_dop_values(self):
        d = dop_from_unit_vectors(self.VECTORS)
        self.assertAlmostEqual(d.pdop, math.sqrt(3.5), places=9)
        self.assertAlmostEqual(d.hdop, math.sqrt(2.0), places=9)
        self.assertAlmostEqual(d.vdop, math.sqrt(1.5), places=9)
        self.assertAlmostEqual(d.tdop, math.sqrt(0.5), places=9)
        self.assertAlmostEqual(d.gdop, 2.0, places=9)

    def test_more_sats_lowers_dop(self):
        d4 = dop_from_unit_vectors(self.VECTORS)
        d8 = dop_from_unit_vectors(self.VECTORS + self.VECTORS)
        self.assertLess(d8.pdop, d4.pdop)

    def test_needs_four_sats(self):
        with self.assertRaises(ValueError):
            dop_from_unit_vectors(self.VECTORS[:3])

    def test_singular_geometry(self):
        with self.assertRaises(ValueError):
            dop_from_unit_vectors([(0, 0, 1)] * 4)

    def test_dop_quality(self):
        d = dop_from_unit_vectors(self.VECTORS)
        self.assertEqual(dop_quality(d), "excellent")


class TestSession(unittest.TestCase):
    def test_mean_and_std(self):
        s = Session()
        for i in range(5):
            s.add(Fix(lat=48.0 + i * 0.001, lon=11.0, height=500.0 + i))
        self.assertEqual(s.count, 5)
        lat, lon, h = s.mean_position()
        self.assertAlmostEqual(lat, 48.002, places=12)
        self.assertAlmostEqual(lon, 11.0, places=12)
        self.assertAlmostEqual(h, 502.0, places=12)
        s_lat, s_lon, s_h = s.std()
        # sample std of 0..4 steps of 0.001 -> sqrt(2.5e-6)
        self.assertAlmostEqual(s_lat, math.sqrt(2.5e-6), places=12)
        self.assertAlmostEqual(s_lon, 0.0, places=12)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            Session().mean_position()
        with self.assertRaises(ValueError):
            Session().std()

    def test_2drms(self):
        s = Session()
        s.add(Fix(lat=48.0, lon=11.0))
        s.add(Fix(lat=48.002, lon=11.0))
        # std lat = 0.001*sqrt(2), lon = 0 -> 2DRMS = 2*sqrt(2)*0.001
        self.assertAlmostEqual(s.accuracy_2drms(), 2 * math.sqrt(2) * 0.001,
                               places=12)
        m = s.horizontal_accuracy_metres(at_lat=48.0)
        self.assertAlmostEqual(m, 2 * math.sqrt(2) * 0.001
                               * 111320.0 * math.cos(math.radians(48.0)),
                               places=6)

    def test_fix_from_gga(self):
        f = Fix.from_gga(parse_gga(GGA))
        self.assertIsNotNone(f)
        self.assertEqual(f.quality, 1)
        bad = parse_gga(GGA.replace(",1,08,", ",0,08,"))
        # checksum now wrong; parse without check
        from gnss.nmea import parse_gga as pg
        g0 = pg("$GPGGA,123519,4807.038,N,01131.000,E,0,08,0.9,"
                "545.4,M,46.9,M,,*00")
        self.assertIsNone(Fix.from_gga(g0))

    def test_assess_quality(self):
        self.assertEqual(assess_quality(4), "rtk_fixed")
        self.assertEqual(assess_quality(5), "rtk_float")
        self.assertEqual(assess_quality(2), "dgps")
        self.assertEqual(assess_quality(0), "no_fix")
        self.assertEqual(assess_quality(4, hdop=9.0), "rtk_fixed_high_dop")


if __name__ == "__main__":
    unittest.main()
