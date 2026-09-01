from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.classification import ImageCategory, index_image_categories
from photovault.catalog.collections import list_collections, list_collection_items
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "category-volume", "Category volume")


class FakeClassifier:
    model_name = "fake-imagenet"

    def classify(self, path: Path, top_k: int):
        return [ImageCategory("tabby cat", 0.9), ImageCategory("pet", 0.1)][:top_k]


class ClassificationTests(unittest.TestCase):
    def test_categories_are_hash_invalidated_catalog_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; root.mkdir()
            (root / "cat.jpg").write_bytes(b"not-decoded-by-fake"); (root / "cat-two.jpg").write_bytes(b"also-not-decoded-by-fake")
            connection = connect(Path(directory) / "catalog.db")
            volume = register_volume(connection, root, FixedProvider()); scan_volume(connection, volume, root)
            first = index_image_categories(connection, FakeClassifier())
            self.assertEqual((first["indexed"], first["errors"]), (2, 0))
            second = index_image_categories(connection, FakeClassifier())
            self.assertEqual((second["skipped"], second["indexed"]), (2, 0))
            category = next(item for item in list_collections(connection) if item.kind == "CATEGORY" and item.title == "tabby cat")
            self.assertEqual(
                {row["filename"] for row in list_collection_items(connection, category.id)},
                {"cat.jpg", "cat-two.jpg"},
            )
            self.assertEqual(index_image_categories(connection, FakeClassifier(), limit=1, offset=1)["skipped"], 1)
            connection.close()
