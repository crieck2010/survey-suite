"""Unit tests for survey-raster. Run with: python -m unittest discover -s tests"""
import math
import unittest

from raster import (
    Raster,
    describe,
    evi,
    histogram,
    index_raster,
    is_nodata,
    iter_windows,
    linear_stretch,
    ndvi,
    ndwi,
    normalized_difference,
    percentile,
    resample,
    same_nodata,
    savi,
)


def grid4():
    return [[r * 4 + c for c in range(4)] for r in range(4)]


class TestNodataHelpers(unittest.TestCase):
    def test_is_nodata(self):
        self.assertTrue(is_nodata(-9999.0, -9999.0))
        self.assertFalse(is_nodata(1.0, -9999.0))
        self.assertTrue(is_nodata(float("nan"), float("nan")))
        self.assertFalse(is_nodata(1.0, float("nan")))
        self.assertFalse(is_nodata(1.0, None))
        self.assertTrue(is_nodata(None, -9999.0))

    def test_same_nodata(self):
        self.assertTrue(same_nodata(float("nan"), float("nan")))
        self.assertTrue(same_nodata(-9999.0, -9999.0))
        self.assertTrue(same_nodata(None, None))
        self.assertFalse(same_nodata(None, -9999.0))
        self.assertFalse(same_nodata(-9999.0, -9998.0))


class TestRasterModel(unittest.TestCase):
    def test_shape(self):
        r = Raster(grid4())
        self.assertEqual(r.shape, (4, 4))
        self.assertEqual((r.height, r.width), (4, 4))

    def test_georeferencing_roundtrip(self):
        t = (100.0, 10.0, 0.0, 200.0, 0.0, -10.0)
        r = Raster(grid4(), transform=t, crs="EPSG:32618")
        x, y = r.rowcol_to_xy(0, 0)
        self.assertAlmostEqual(x, 105.0)
        self.assertAlmostEqual(y, 195.0)
        self.assertEqual(r.xy_to_rowcol(105.0, 195.0), (0, 0))
        self.assertEqual(r.xy_to_rowcol(115.0, 185.0), (1, 1))

    def test_xy_outside_raises(self):
        r = Raster(grid4(), transform=(100.0, 10.0, 0, 200.0, 0, -10.0))
        with self.assertRaises(ValueError):
            r.xy_to_rowcol(0.0, 0.0)

    def test_window(self):
        t = (100.0, 10.0, 0.0, 200.0, 0.0, -10.0)
        r = Raster(grid4(), transform=t, crs="EPSG:32618", nodata=-9999.0)
        w = r.window(1, 1, 2, 2)
        self.assertEqual(w.shape, (2, 2))
        self.assertEqual(w.data, [[5, 6], [9, 10]])
        self.assertEqual(w.transform, (110.0, 10.0, 0.0, 190.0, 0.0, -10.0))
        self.assertEqual(w.crs, "EPSG:32618")
        self.assertEqual(w.nodata, -9999.0)

    def test_window_out_of_bounds_raises(self):
        r = Raster(grid4())
        with self.assertRaises(ValueError):
            r.window(3, 3, 2, 2)

    def test_iter_windows_covers_exactly_once(self):
        covered = []
        n = 0
        for row, col, w, h in iter_windows(10, 10, tile=4):
            n += 1
            for r in range(row, row + h):
                for c in range(col, col + w):
                    covered.append((r, c))
        self.assertEqual(n, 9)
        self.assertEqual(len(covered), 100)
        self.assertEqual(len(set(covered)), 100)

    def test_iter_windows_bad_args(self):
        with self.assertRaises(ValueError):
            list(iter_windows(10, 10, tile=0))
        with self.assertRaises(ValueError):
            list(iter_windows(10, 10, tile=8, overlap=4))

    def test_windows_method(self):
        r = Raster(grid4())
        tiles = list(r.windows(tile=2))
        self.assertEqual(len(tiles), 4)
        self.assertTrue(all(t.shape == (2, 2) for t in tiles))


class TestIndices(unittest.TestCase):
    def test_ndvi(self):
        out = ndvi([[0.8]], [[0.2]])
        self.assertAlmostEqual(out[0][0], 0.6, places=9)

    def test_normalized_difference(self):
        out = normalized_difference([[0.6]], [[0.2]])
        self.assertAlmostEqual(out[0][0], 0.5, places=9)

    def test_ndwi(self):
        out = ndwi([[0.6]], [[0.2]])
        self.assertAlmostEqual(out[0][0], 0.5, places=9)

    def test_evi(self):
        out = evi([[0.5]], [[0.2]], [[0.1]])
        self.assertAlmostEqual(out[0][0], 0.75 / 1.95, places=9)

    def test_savi(self):
        out = savi([[0.8]], [[0.2]])
        self.assertAlmostEqual(out[0][0], 0.6, places=9)

    def test_nodata_propagates(self):
        out = ndvi([[0.8, -9999.0]], [[0.2, 0.3]], nodata=-9999.0)
        self.assertAlmostEqual(out[0][0], 0.6, places=9)
        self.assertEqual(out[0][1], -9999.0)

    def test_zero_denominator_is_nan(self):
        out = ndvi([[0.0]], [[0.0]])
        self.assertTrue(math.isnan(out[0][0]))

    def test_shape_mismatch_raises(self):
        with self.assertRaises(ValueError):
            ndvi([[0.8]], [[0.2, 0.3]])

    def test_index_raster_keeps_georeferencing(self):
        t = (100.0, 10.0, 0.0, 200.0, 0.0, -10.0)
        nir = Raster([[0.8]], transform=t, crs="EPSG:32618")
        red = Raster([[0.2]], transform=t, crs="EPSG:32618")
        out = index_raster(nir, red)
        self.assertAlmostEqual(out.data[0][0], 0.6, places=9)
        self.assertEqual(out.transform, t)
        self.assertEqual(out.crs, "EPSG:32618")

    def test_index_raster_misregistered_raises(self):
        nir = Raster([[0.8]], transform=(0, 10, 0, 0, 0, -10))
        red = Raster([[0.2]], transform=(5, 10, 0, 0, 0, -10))
        with self.assertRaises(ValueError):
            index_raster(nir, red)


class TestStats(unittest.TestCase):
    def test_describe(self):
        s = describe([[1, 2], [3, 4]])
        self.assertEqual((s.minimum, s.maximum), (1, 4))
        self.assertAlmostEqual(s.mean, 2.5, places=9)
        self.assertAlmostEqual(s.std, math.sqrt(1.25), places=9)
        self.assertEqual((s.count, s.nodata_count), (4, 0))

    def test_describe_with_nodata(self):
        s = describe([[1, -9999], [3, 4]], nodata=-9999)
        self.assertEqual((s.count, s.nodata_count), (3, 1))
        self.assertAlmostEqual(s.mean, 8 / 3, places=9)

    def test_describe_empty_raises(self):
        with self.assertRaises(ValueError):
            describe([[-9999]], nodata=-9999)

    def test_histogram(self):
        self.assertEqual(histogram([[0, 1], [2, 3]], bins=4,
                                   value_range=(0, 4)), [1, 1, 1, 1])

    def test_percentile(self):
        self.assertAlmostEqual(percentile([[1, 2], [3, 4]], 50), 2.5, places=9)
        self.assertAlmostEqual(percentile([[1, 2], [3, 4]], 0), 1.0, places=9)
        self.assertAlmostEqual(percentile([[1, 2], [3, 4]], 100), 4.0, places=9)

    def test_linear_stretch(self):
        out = linear_stretch([[0, 50, 100]], p_low=0, p_high=100,
                             out_min=0, out_max=1)
        self.assertAlmostEqual(out[0][0], 0.0, places=9)
        self.assertAlmostEqual(out[0][1], 0.5, places=9)
        self.assertAlmostEqual(out[0][2], 1.0, places=9)

    def test_linear_stretch_keeps_nodata(self):
        out = linear_stretch([[0, -9999]], p_low=0, p_high=100, nodata=-9999)
        self.assertEqual(out[0][1], -9999)


class TestResample(unittest.TestCase):
    def test_nearest_upsample(self):
        out = resample([[1, 2], [3, 4]], 4, 4, method="nearest")
        self.assertEqual(out[0][0], 1)
        self.assertEqual(out[0][3], 2)
        self.assertEqual(out[3][0], 3)
        self.assertEqual(out[3][3], 4)

    def test_bilinear_corners_and_centre(self):
        out = resample([[0, 10], [20, 30]], 3, 3, method="bilinear")
        self.assertAlmostEqual(out[0][0], 0.0, places=9)
        self.assertAlmostEqual(out[0][2], 10.0, places=9)
        self.assertAlmostEqual(out[2][0], 20.0, places=9)
        self.assertAlmostEqual(out[2][2], 30.0, places=9)
        self.assertAlmostEqual(out[1][1], 15.0, places=9)

    def test_bilinear_skips_nodata(self):
        out = resample([[0, -9999], [20, 30]], 3, 3,
                       method="bilinear", nodata=-9999)
        # Centre blends the three valid neighbours with renormalized weights.
        self.assertAlmostEqual(out[1][1], (0 + 20 + 30) / 3, places=9)

    def test_bad_method_raises(self):
        with self.assertRaises(ValueError):
            resample([[1]], 2, 2, method="cubic")

    def test_bad_dims_raise(self):
        with self.assertRaises(ValueError):
            resample([[1]], 0, 2)


if __name__ == "__main__":
    unittest.main()
