import tempfile
import unittest
from pathlib import Path

from photovault.catalog.organization import (
    add_assets_to_topic_section,
    create_event,
    create_topic_section,
    list_topic_sections,
    remove_assets_from_topic_section,
)
from photovault.database.connection import connect


class TopicSectionTests(unittest.TestCase):
    def test_sections_are_independent_memberships_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            db = connect(Path(temp) / "catalog.db")
            self.addCleanup(db.close)
            topic_id = create_event(db, "Trip", start_datetime="2026-04-18")
            db.executemany(
                "INSERT INTO assets(id, media_type, created_at, updated_at) VALUES (?, 'image', datetime('now'), datetime('now'))",
                [("asset-a",), ("asset-b",), ("asset-c",)],
            )
            db.commit()

            section_id = create_topic_section(db, topic_id, "Kew Gardens", ["asset-a", "asset-b"])
            self.assertEqual(list_topic_sections(db, topic_id)[0]["item_count"], 2)
            self.assertEqual(add_assets_to_topic_section(db, section_id, ["asset-b", "asset-c"]), 1)
            self.assertEqual(add_assets_to_topic_section(db, section_id, ["asset-c"]), 0)
            self.assertEqual(remove_assets_from_topic_section(db, section_id, ["asset-a", "missing"]), 1)
            self.assertEqual(
                [row[0] for row in db.execute("SELECT asset_id FROM topic_section_assets WHERE section_id=?", (section_id,))],
                ["asset-b", "asset-c"],
            )

    def test_unknown_asset_is_ignored_and_unknown_topic_or_section_is_rejected(self):
        db = connect(":memory:")
        self.addCleanup(db.close)
        topic_id = create_event(db, "Trip")
        section_id = create_topic_section(db, topic_id, "Arrival")
        self.assertEqual(add_assets_to_topic_section(db, section_id, ["does-not-exist"]), 0)
        with self.assertRaises(ValueError):
            create_topic_section(db, "missing", "Broken")
        with self.assertRaises(ValueError):
            add_assets_to_topic_section(db, "missing", [])


if __name__ == "__main__":
    unittest.main()
