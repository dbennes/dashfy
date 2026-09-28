from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from unittest import TestCase

from PIL import Image, ImageDraw

from apps.vessels.water_routes import DATA, WaterMask, estimated_water_routes, route_pair, water_mask


class WaterRouteTests(TestCase):
    def assert_water_path(self, mask, points):
        self.assertIsNotNone(points)
        for a, b in zip(points, points[1:]):
            self.assertTrue(mask.clear(a, b), (a, b))

    def test_island_detour_preserves_hole_and_never_cuts_corners(self):
        image = Image.new("1", (128, 128), 1)
        ImageDraw.Draw(image).rectangle((45, 30, 85, 100), fill=0)
        mask = WaterMask({"zoom": 12, "tile_size": 256, "origin_tile": [0, 0]}, image)
        self.assertFalse(mask.clear((10, 60), (110, 60)))
        route = mask.path((10, 60), (110, 60))
        self.assertGreater(len(route), 2)
        self.assert_water_path(mask, route)

    def test_disconnected_water_and_outside_coverage_are_not_bridged(self):
        image = Image.new("1", (64, 64), 1)
        ImageDraw.Draw(image).rectangle((30, 0, 35, 63), fill=0)
        mask = WaterMask({"zoom": 12, "tile_size": 256, "origin_tile": [0, 0]}, image)
        self.assertIsNone(mask.path((5, 30), (55, 30)))
        self.assertIsNone(mask.path((-10, 30), (55, 30)))

    def test_real_sparse_aveon_fixes_follow_channels_in_both_directions(self):
        mask = water_mask()
        a, b = (4.7942467, 6.9417582), (4.615082, 7.168013)
        self.assertFalse(mask.clear(mask.pixel(*a), mask.pixel(*b)))
        for first, last in ((a, b), (b, a)):
            route = route_pair(first, last)
            self.assertGreater(len(route), 10)
            self.assert_water_path(mask, [mask.pixel(*p) for p in route])
            # Quay uncertainty never moves the real observation; route endpoints
            # stay within the explicitly bounded nearby-water search radius.
            self.assertLess(abs(route[0][0] - first[0]), .003)
            self.assertLess(abs(route[-1][1] - last[1]), .003)

    def test_bonga_to_aveon_and_old_offshore_fixes_have_connected_water_routes(self):
        mask = water_mask()
        fixes = [(4.5575266, 4.6164432), (3.8, 6.7), (4.1, 7.1),
                 (4.541847, 7.203438), (4.615082, 7.168013), (4.7942467, 6.9417582)]
        for a, b in list(zip(fixes, fixes[1:])) + [(fixes[0], fixes[-1])]:
            route = route_pair(a, b)
            self.assertIsNotNone(route, (a, b))
            self.assert_water_path(mask, [mask.pixel(*p) for p in route])

    def test_estimates_are_separate_from_unchanged_observations_and_reuse_geometry(self):
        now = datetime(2026, 9, 28, tzinfo=timezone.utc)
        positions = [dict(id=1, latitude=4.615082, longitude=7.168013, timestamp=now),
                     dict(id=2, latitude=4.541847, longitude=7.203438, timestamp=now)]
        original = deepcopy(positions)
        first = estimated_water_routes(positions)
        hits = route_pair.cache_info().hits
        second = estimated_water_routes(positions)
        self.assertEqual(first, second)
        self.assertGreater(route_pair.cache_info().hits, hits)
        self.assertEqual(positions, original)
        self.assertEqual(first["kind"], "estimated_water_route")
        self.assertEqual(first["segments"][0]["timestamp"], now)
        self.assertEqual(first["unresolved"], 0)

    def test_unmapped_pair_and_stationary_reports_do_not_invent_paths(self):
        rows = [dict(id=1, latitude=0, longitude=0, timestamp="2026-09-28T00:00:00Z"),
                dict(id=2, latitude=1, longitude=1, timestamp="2026-09-28T01:00:00Z")]
        result = estimated_water_routes(rows)
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["unresolved"], 1)
        self.assertEqual(estimated_water_routes([rows[0], rows[0]])["unresolved"], 0)

    def test_bundled_mask_matches_provenance_checksum(self):
        self.assertEqual(hashlib.sha256((DATA / "niger-delta-water.png").read_bytes()).hexdigest(),
                         water_mask().meta["sha256"])
