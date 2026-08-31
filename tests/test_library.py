from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.favourites import set_favourite
from photovault.catalog.library import LibraryQuery, count_library_items, list_library_items
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "library-volume", "Library volume")


class LibraryTests(unittest.TestCase):
    def test_catalog_query_filters_without_rescanning_or_hiding_offline_media(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; (root / "DCIM/Camera").mkdir(parents=True)
            (root / "DCIM/Camera/cat.jpg").write_bytes(b"cat")
            (root / "DCIM/Camera/clip.mp4").write_bytes(b"video")
            connection = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider())
            scan_volume(connection, volume_id, root)
            cat_asset = connection.execute("SELECT asset_id FROM asset_locations WHERE filename='cat.jpg'").fetchone()[0]
            set_favourite(connection, cat_asset)
            favourites = LibraryQuery(folder_prefix="DCIM/Camera", media_type="IMAGE", favourite_only=True)
            rows = list_library_items(connection, favourites)
            self.assertEqual((len(rows), rows[0]["filename"], rows[0]["is_favourite"]), (1, "cat.jpg", 1))
            self.assertEqual(count_library_items(connection, favourites), 1)
            connection.execute("UPDATE volumes SET status='OFFLINE' WHERE id=?", (volume_id,)); connection.commit()
            offline = list_library_items(connection, LibraryQuery(search="clip"))
            self.assertEqual((offline[0]["filename"], offline[0]["volume_status"]), ("clip.mp4", "OFFLINE"))
            connection.close()
