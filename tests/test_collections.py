from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.collections import add_to_user_collection, collection_query, count_collection_items, create_user_collection, list_collection_items, list_collections
from photovault.catalog.favourites import set_favourite
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "collections-volume", "Collections volume")


class CollectionTests(unittest.TestCase):
    def test_folder_and_favourite_collections_are_catalog_views(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; (root / "DCIM/Camera").mkdir(parents=True); (root / "Download").mkdir()
            (root / "DCIM/Camera/cat.jpg").write_bytes(b"cat"); (root / "Download/dog.jpg").write_bytes(b"dog")
            connection = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider()); scan_volume(connection, volume_id, root)
            cat_asset = connection.execute("SELECT asset_id FROM asset_locations WHERE filename='cat.jpg'").fetchone()[0]
            set_favourite(connection, cat_asset)
            collections = {collection.id: collection for collection in list_collections(connection)}
            self.assertEqual(collections["folder:DCIM/Camera"].item_count, 1)
            self.assertEqual(collections["favourites"].item_count, 1)
            self.assertEqual(list_collection_items(connection, "folder:DCIM/Camera")[0]["filename"], "cat.jpg")
            self.assertEqual(count_collection_items(connection, "favourites"), 1)
            self.assertTrue(collection_query(connection, "favourites").favourite_only)
            with self.assertRaises(ValueError):
                collection_query(connection, "semantic:invented")

    def test_user_album_membership_is_catalog_only_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "catalog.db")
            root = Path(temp) / "photos"
            root.mkdir()
            (root / "album.jpg").write_bytes(b"album")
            volume_id = register_volume(connection, root, FixedProvider())
            scan_volume(connection, volume_id, root)
            asset_id = connection.execute("SELECT id FROM assets").fetchone()[0]
            collection_id = create_user_collection(connection, "Trip")
            self.assertEqual(add_to_user_collection(connection, collection_id, [asset_id]), 1)
            self.assertEqual(add_to_user_collection(connection, collection_id, [asset_id]), 0)
            self.assertEqual(list_collection_items(connection, collection_id)[0]["filename"], "album.jpg")
            connection.execute(
                "INSERT INTO thumbnails(asset_id, version, path, width, height, created_at) VALUES (?, 'v1-320', ?, 320, 240, datetime('now'))",
                (asset_id, str(root / "album-thumb.jpg")),
            )
            connection.commit()
            album = next(item for item in list_collections(connection) if item.id == collection_id)
            self.assertEqual(album.cover_path, str(root / "album-thumb.jpg"))
            self.assertEqual((root / "album.jpg").read_bytes(), b"album")
            connection.close()
