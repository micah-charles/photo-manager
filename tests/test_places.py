from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.places import cluster_places, distance_meters
from photovault.database.connection import connect


class PlacesTests(unittest.TestCase):
    def test_haversine_and_offline_place_clustering(self) -> None:
        self.assertLess(distance_meters(51.5000, -0.1200, 51.5005, -0.1200), 100)
        with tempfile.TemporaryDirectory() as temp:
            db = connect(Path(temp) / "catalog.db")
            db.execute("INSERT INTO assets(id, media_type, created_at, updated_at) VALUES ('a', 'IMAGE', 'now', 'now')")
            db.execute("INSERT INTO assets(id, media_type, created_at, updated_at) VALUES ('b', 'IMAGE', 'now', 'now')")
            db.execute("INSERT INTO assets(id, media_type, created_at, updated_at) VALUES ('c', 'IMAGE', 'now', 'now')")
            db.executemany("INSERT INTO gps_metadata(asset_id, latitude, longitude, extracted_at) VALUES (?, ?, ?, 'now')", [
                ("a", 51.5000, -0.1200), ("b", 51.5005, -0.1200), ("c", 52.0000, -0.1200),
            ])
            clusters = cluster_places(db, 100)
            self.assertEqual(sorted(len(cluster.asset_ids) for cluster in clusters), [1, 2])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM place_cluster_members").fetchone()[0], 3)
            self.assertIsNone(db.execute("SELECT label FROM place_clusters ORDER BY id LIMIT 1").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
