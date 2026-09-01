from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional photo feature
    Image = None

from photovault.catalog.perceptual import (
    BKTree,
    find_visual_duplicate_groups,
    hamming_distance,
    index_perceptual_hashes,
)
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test_uuid", "visual-test-disk", "visual-test-disk")


class PerceptualTests(unittest.TestCase):
    def test_hamming_and_bk_tree(self) -> None:
        self.assertEqual(hamming_distance(0b1010, 0b1001), 2)
        tree = BKTree()
        tree.add(0b0000, "zero")
        tree.add(0b0011, "three")
        tree.add(0b1111, "fifteen")
        self.assertEqual({item for _, item in tree.query(0b0001, 2)}, {"zero", "three"})

    def test_index_and_group_reencoded_images_without_file_mutation(self) -> None:
        if Image is None:
            self.skipTest("Pillow is not installed")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "photos"
            root.mkdir()
            image = Image.new("RGB", (96, 96), "#d65a43")
            image.save(root / "first.jpg", quality=95)
            image.save(root / "second.jpg", quality=55)
            before = {path.name: path.read_bytes() for path in root.glob("*.jpg")}
            db = connect(Path(temp) / "catalog.db")
            self.addCleanup(db.close)
            volume_id = register_volume(db, root, FixedProvider())
            scan_volume(db, volume_id, root)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 2)
            result = index_perceptual_hashes(db, volume_id)
            self.assertEqual(result["assets"], 2)
            self.assertEqual(result["dhash64"], 2)
            self.assertEqual(result["phash64"], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM perceptual_hashes").fetchone()[0], 4)
            groups = find_visual_duplicate_groups(db, "dhash64", 0, volume_id)
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0]["members"]), 2)
            self.assertEqual(before, {path.name: path.read_bytes() for path in root.glob("*.jpg")})
            self.assertEqual(db.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 0)
            db.close()

    def test_index_limit(self) -> None:
        if Image is None:
            self.skipTest("Pillow is not installed")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "photos"
            root.mkdir()
            for name, colour in (("a.jpg", "red"), ("b.jpg", "blue")):
                Image.new("RGB", (32, 32), colour).save(root / name)
            db = connect(Path(temp) / "catalog.db")
            self.addCleanup(db.close)
            volume_id = register_volume(db, root, FixedProvider())
            scan_volume(db, volume_id, root)
            result = index_perceptual_hashes(db, volume_id, ("dhash64",), limit=1)
            self.assertEqual(result["assets"], 1)
            self.assertEqual(result["dhash64"], 1)
            db.close()


if __name__ == "__main__":
    unittest.main()
