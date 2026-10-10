"""Unit tests for survey-pointcloud. Run with: python -m unittest discover -s tests"""
import math
import unittest

from pointcloud import (
    GROUND,
    UNCLASSIFIED,
    Point,
    PointCloud,
    as_point,
    classify_ground_grid,
    grid_maximum,
    grid_minimum,
    interpolate_idw,
    iter_chunks,
    volume_between,
    volume_grid,
    voxel_thin,
    xyz,
)


class TestPointModel(unittest.TestCase):
    def test_xyz_from_point(self):
        self.assertEqual(xyz(Point(1, 2, 3)), (1, 2, 3))

    def test_xyz_from_tuple(self):
        self.assertEqual(xyz((1.0, 2.0, 3.0, 99.0)), (1.0, 2.0, 3.0))

    def test_as_point_defaults(self):
        p = as_point((1.0, 2.0, 3.0))
        self.assertIsInstance(p, Point)
        self.assertEqual(p.classification, UNCLASSIFIED)
        self.assertEqual(p.intensity, 0.0)

    def test_as_point_passthrough(self):
        p = Point(1, 2, 3, classification=GROUND)
        self.assertIs(as_point(p), p)


class TestPointCloud(unittest.TestCase):
    def setUp(self):
        self.cloud = PointCloud([
            Point(0, 0, 10, classification=GROUND),
            Point(5, 5, 20, classification=UNCLASSIFIED),
            Point(10, 0, 30, classification=GROUND),
        ], crs="EPSG:32618")

    def test_len_and_crs(self):
        self.assertEqual(len(self.cloud), 3)
        self.assertEqual(self.cloud.crs, "EPSG:32618")

    def test_bounds(self):
        self.assertEqual(self.cloud.bounds(), (0, 0, 10, 10, 5, 30))

    def test_describe(self):
        s = self.cloud.describe()
        self.assertEqual(s.count, 3)
        self.assertAlmostEqual(s.mean_z, 20.0)
        self.assertEqual(s.classes, {GROUND: 2, UNCLASSIFIED: 1})

    def test_crop(self):
        c = self.cloud.crop(0, 0, 6, 6)
        self.assertEqual(len(c), 2)
        self.assertEqual(c.crs, "EPSG:32618")

    def test_filter_classification(self):
        g = self.cloud.filter_classification([GROUND])
        self.assertEqual(len(g), 2)
        self.assertTrue(all(p.classification == GROUND for p in g.points))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            PointCloud().bounds()
        with self.assertRaises(ValueError):
            PointCloud().describe()


class TestThinningAndChunks(unittest.TestCase):
    def test_voxel_thin_lowest(self):
        pts = [(0.1, 0.1, 5.7), (0.2, 0.2, 5.3), (0.15, 0.15, 5.9),
               (5.0, 5.0, 1.0)]
        out = voxel_thin(pts, 1.0, keep="lowest")
        self.assertEqual(len(out), 2)
        by_x = sorted(out, key=lambda p: p.x)
        self.assertAlmostEqual(by_x[0].z, 5.3)  # lowest in voxel (0, 0, 5)
        self.assertAlmostEqual(by_x[1].z, 1.0)

    def test_voxel_thin_first(self):
        pts = [(0.1, 0.1, 5.7), (0.2, 0.2, 5.3)]
        out = voxel_thin(pts, 1.0, keep="first")
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0].z, 5.7)

    def test_voxel_thin_bad_args(self):
        with self.assertRaises(ValueError):
            voxel_thin([(0, 0, 0)], 0)
        with self.assertRaises(ValueError):
            voxel_thin([(0, 0, 0)], 1.0, keep="median")

    def test_iter_chunks(self):
        chunks = list(iter_chunks(list(range(10)), 4))
        self.assertEqual([len(c) for c in chunks], [4, 4, 2])
        self.assertEqual(sum(chunks, []), list(range(10)))

    def test_iter_chunks_bad_size(self):
        with self.assertRaises(ValueError):
            list(iter_chunks([1, 2], 0))


class TestGroundClassification(unittest.TestCase):
    def test_simple_scene(self):
        # Two cells, each with ground (~0) and a roof (+10).
        pts = [
            (1, 1, 0.05), (2, 2, -0.03), (1.5, 1.5, 10.0),
            (12, 1, 0.02), (13, 2, 0.08), (12.5, 1.5, 10.0),
        ]
        out = classify_ground_grid(pts, cell_size=10.0, threshold=0.5)
        ground = [p for p in out if p.classification == GROUND]
        roofs = [p for p in out if p.classification != GROUND]
        self.assertEqual(len(ground), 4)
        self.assertEqual(len(roofs), 2)
        self.assertTrue(all(p.z < 1.0 for p in ground))
        self.assertTrue(all(p.z > 9.0 for p in roofs))

    def test_originals_untouched(self):
        pts = [Point(1, 1, 0.05)]
        out = classify_ground_grid(pts, cell_size=10.0, threshold=0.5)
        self.assertEqual(pts[0].classification, UNCLASSIFIED)
        self.assertEqual(out[0].classification, GROUND)

    def test_empty(self):
        self.assertEqual(classify_ground_grid([], 10.0, 0.5), [])

    def test_bad_args(self):
        with self.assertRaises(ValueError):
            classify_ground_grid([(0, 0, 0)], 0, 0.5)
        with self.assertRaises(ValueError):
            classify_ground_grid([(0, 0, 0)], 10, -1)


class TestDem(unittest.TestCase):
    def test_grid_minimum_and_maximum(self):
        pts = [(0.5, 0.5, 1.0), (0.6, 0.6, 5.0), (1.5, 0.5, 3.0)]
        mn = grid_minimum(pts, 0, 0, 1.0, 2, 1)
        mx = grid_maximum(pts, 0, 0, 1.0, 2, 1)
        self.assertEqual(mn[0], [1.0, 3.0])
        self.assertEqual(mx[0], [5.0, 3.0])

    def test_grid_empty_cell_is_nodata(self):
        g = grid_minimum([(1.5, 1.5, 1.0)], 0, 0, 1.0, 2, 2)
        self.assertTrue(math.isnan(g[0][0]))
        self.assertAlmostEqual(g[1][1], 1.0)

    def test_grid_out_of_bounds_ignored(self):
        g = grid_minimum([(-5.0, -5.0, 1.0)], 0, 0, 1.0, 1, 1)
        self.assertTrue(math.isnan(g[0][0]))

    def test_idw_single_point(self):
        g = interpolate_idw([(0.5, 0.5, 7.0)], 0, 0, 1.0, 1, 1)
        self.assertAlmostEqual(g[0][0], 7.0, places=9)

    def test_idw_two_points(self):
        g = interpolate_idw([(0, 0, 0.0), (2, 0, 10.0)], 0, 0, 1.0, 2, 1)
        self.assertAlmostEqual(g[0][0], 4 / 2.4, places=9)
        self.assertAlmostEqual(g[0][1], 20 / 2.4, places=9)

    def test_idw_radius(self):
        g = interpolate_idw([(10.0, 10.0, 5.0)], 0, 0, 1.0, 1, 1,
                            radius=1.0)
        self.assertTrue(math.isnan(g[0][0]))

    def test_idw_bad_args(self):
        with self.assertRaises(ValueError):
            interpolate_idw([(0, 0, 0)], 0, 0, 0, 1, 1)


class TestVolumes(unittest.TestCase):
    def test_volume_grid_cut(self):
        cut, fill, net = volume_grid([[12, 12], [12, 12]], 10.0, 4.0)
        self.assertAlmostEqual(cut, 32.0, places=9)
        self.assertAlmostEqual(fill, 0.0, places=9)
        self.assertAlmostEqual(net, 32.0, places=9)

    def test_volume_grid_mixed(self):
        cut, fill, net = volume_grid([[12, 8]], 10.0, 4.0)
        self.assertAlmostEqual(cut, 8.0, places=9)
        self.assertAlmostEqual(fill, 8.0, places=9)
        self.assertAlmostEqual(net, 0.0, places=9)

    def test_volume_grid_skips_nodata(self):
        cut, fill, net = volume_grid([[12, float("nan")]], 10.0, 4.0)
        self.assertAlmostEqual(cut, 8.0, places=9)

    def test_volume_between(self):
        cut, fill, net = volume_between([[12, 12]], [[10, 10]], 4.0)
        self.assertAlmostEqual(cut, 16.0, places=9)
        self.assertAlmostEqual(net, 16.0, places=9)

    def test_volume_between_mixed(self):
        cut, fill, net = volume_between([[12, 8]], [[10, 10]], 4.0)
        self.assertAlmostEqual(cut, 8.0, places=9)
        self.assertAlmostEqual(fill, 8.0, places=9)
        self.assertAlmostEqual(net, 0.0, places=9)

    def test_volume_bad_area(self):
        with self.assertRaises(ValueError):
            volume_grid([[12]], 10.0, 0)


if __name__ == "__main__":
    unittest.main()
