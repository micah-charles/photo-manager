from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from photovault.catalog.organization import add_assets_to_event, create_event
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity
from photovault.web.culling import decisions, photo_page, set_decision


class _Provider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "culling-test-volume", "Culling test volume")


class CullingApiTests(unittest.TestCase):
    def test_topic_photo_pages_and_picks_are_bounded_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "photos"
            root.mkdir()
            for index in range(3):
                Image.new("RGB", (64, 48), (index * 40, 80, 120)).save(root / f"photo-{index}.jpg")
            db = connect(Path(directory) / "catalog.db")
            self.addCleanup(db.close)
            volume_id = register_volume(db, root, _Provider())
            scan_volume(db, volume_id, root)
            asset_ids = [str(row[0]) for row in db.execute("SELECT id FROM assets ORDER BY id")]
            topic_id = create_event(db, "Culling test")
            add_assets_to_event(db, topic_id, asset_ids)

            first = photo_page(db, topic_id, limit=2)
            self.assertEqual(first["total"], 3)
            self.assertEqual(len(first["items"]), 2)
            self.assertEqual(first["next_offset"], 2)

            set_decision(db, topic_id, asset_ids[0], "pick")
            set_decision(db, topic_id, asset_ids[1], "reject")
            self.assertEqual(decisions(db, topic_id), {asset_ids[0]: "pick", asset_ids[1]: "reject"})
            picked = photo_page(db, topic_id, picks=True)
            self.assertEqual(picked["total"], 1)
            self.assertEqual(picked["items"][0]["asset_id"], asset_ids[0])

            set_decision(db, topic_id, asset_ids[0], "clear")
            self.assertEqual(photo_page(db, topic_id, picks=True)["total"], 0)


if __name__ == "__main__":
    unittest.main()
