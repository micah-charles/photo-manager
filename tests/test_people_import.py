from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.collections import list_collections, list_collection_items
from photovault.catalog.people_import import import_macos_vision_features
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "people-volume", "People volume")


class PeopleImportTests(unittest.TestCase):
    def test_vision_import_creates_replaceable_person_collection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; root.mkdir(); image = root / "face.jpg"; image.write_bytes(b"face")
            connection = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider()); scan_volume(connection, volume_id, root)
            report = import_macos_vision_features(connection, {"images": [{"path": str(image), "face_count": 1, "person_ids": [4]}]})
            self.assertEqual((report.people, report.matched_assets, report.unmatched_paths), (1, 1, 0))
            person = next(item for item in list_collections(connection) if item.kind == "PERSON")
            self.assertEqual(list_collection_items(connection, person.id)[0]["filename"], "face.jpg")
            replacement = import_macos_vision_features(connection, {"images": []})
            self.assertEqual(replacement.people, 0)
            self.assertFalse(any(item.kind == "PERSON" for item in list_collections(connection)))
            connection.close()
