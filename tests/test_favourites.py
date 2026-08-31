from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.favourites import list_favourites, remove_favourite, set_favourite
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "favourites-volume", "Favourites volume")


class FavouritesTests(unittest.TestCase):
    def test_favourite_is_persistent_catalog_metadata_without_file_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; root.mkdir()
            image = root / "photo.jpg"; payload = b"original image bytes"; image.write_bytes(payload)
            connection = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider())
            scan_volume(connection, volume_id, root)
            asset_id = connection.execute("SELECT asset_id FROM asset_locations").fetchone()[0]
            set_favourite(connection, asset_id, "keep")
            favourite = list_favourites(connection)[0]
            self.assertEqual((favourite["asset_id"], favourite["note"], favourite["filename"]), (asset_id, "keep", "photo.jpg"))
            self.assertEqual(image.read_bytes(), payload)
            self.assertTrue(remove_favourite(connection, asset_id))
            self.assertFalse(list_favourites(connection))
            connection.close()


if __name__ == "__main__":
    unittest.main()
