from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.dashboard import dashboard_metrics
from photovault.catalog.favourites import set_favourite
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "dashboard-volume", "Dashboard volume")


class DashboardTests(unittest.TestCase):
    def test_metrics_are_catalog_only_and_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; root.mkdir()
            (root / "image.jpg").write_bytes(b"image")
            (root / "clip.mp4").write_bytes(b"video")
            connection = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider())
            scan_volume(connection, volume_id, root)
            asset_id = connection.execute("SELECT asset_id FROM asset_locations WHERE filename='image.jpg'").fetchone()[0]
            set_favourite(connection, asset_id)
            metrics = dashboard_metrics(connection)
            self.assertEqual((metrics.assets, metrics.images, metrics.videos, metrics.volumes, metrics.connected_volumes, metrics.favourites), (2, 1, 1, 1, 1, 1))
            self.assertGreater(metrics.catalog_bytes, 0)
            connection.close()
