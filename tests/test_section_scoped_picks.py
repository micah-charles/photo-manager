from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from photovault.catalog.organization import add_assets_to_event, create_event, create_topic_section
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity
from photovault.web.culling import decisions, photo_page, set_decision


class _Provider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "section-picks-volume", "Section picks volume")


class SectionScopedPickTests(unittest.TestCase):
    def test_same_photo_can_be_picked_and_unpicked_independently(self) -> None:
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
            topic_id = create_event(db, "Section pick test")
            add_assets_to_event(db, topic_id, asset_ids)
            first = create_topic_section(db, topic_id, "Flower 01", asset_ids[:2])
            second = create_topic_section(db, topic_id, "Flower 02", [asset_ids[0], asset_ids[2]])

            set_decision(db, topic_id, asset_ids[0], "pick")
            self.assertEqual(photo_page(db, topic_id, first, picks=True)["total"], 1)
            self.assertEqual(photo_page(db, topic_id, second, picks=True)["total"], 1)

            set_decision(db, topic_id, asset_ids[0], "clear", section=first)
            self.assertEqual(photo_page(db, topic_id, first, picks=True)["total"], 0)
            self.assertEqual(photo_page(db, topic_id, second, picks=True)["total"], 1)
            self.assertEqual(decisions(db, topic_id, first)[asset_ids[0]], "clear")
            self.assertEqual(decisions(db, topic_id, second)[asset_ids[0]], "pick")
            self.assertEqual(decisions(db, topic_id)[asset_ids[0]], "pick")

            with self.assertRaisesRegex(ValueError, "not in this section"):
                set_decision(db, topic_id, asset_ids[2], "pick", section=first)


if __name__ == "__main__":
    unittest.main()
