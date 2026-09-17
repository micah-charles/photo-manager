import unittest

from photovault.catalog.organization import (
    apply_topic_section_suggestions,
    create_event,
    create_topic_section,
    delete_topic_section,
    list_topic_sections,
    merge_topic_sections,
    move_topic_picks,
    rename_topic_section,
    reorder_topic_sections,
    split_topic_section,
    topic_organise_state,
)
from photovault.database.connection import connect
from photovault.web.server import STATIC_ROOT


class OrganisePicksTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")
        self.topic = create_event(self.db, "Garden trip")
        self.assets = [f"asset-{index}" for index in range(1, 7)]
        self.db.execute(
            """INSERT INTO volumes(
                id, display_name, identity_kind, identity_value, first_seen,
                last_seen, status
            ) VALUES ('volume-1', 'Test volume', 'test', 'test-volume',
                      datetime('now'), datetime('now'), 'CONNECTED')"""
        )
        self.db.executemany(
            "INSERT INTO assets(id, media_type, created_at, updated_at) VALUES (?, 'IMAGE', datetime('now'), datetime('now'))",
            [(asset_id,) for asset_id in self.assets],
        )
        self.db.executemany(
            """INSERT INTO asset_locations(
                asset_id, volume_id, relative_path, filename, size_bytes,
                modified_ns, capture_date
            ) VALUES (?, 'volume-1', ?, ?, 1, 1, datetime('now'))""",
            [(asset_id, f"{asset_id}.jpg", f"{asset_id}.jpg") for asset_id in self.assets],
        )
        self.db.executemany(
            "INSERT INTO event_assets(event_id, asset_id, membership_source, created_at) VALUES (?, ?, 'manual', datetime('now'))",
            [(self.topic, asset_id) for asset_id in self.assets],
        )
        self.db.executemany(
            "INSERT INTO topic_culling(topic_id, asset_id, decision, updated_at) VALUES (?, ?, 'pick', datetime('now'))",
            [(self.topic, asset_id) for asset_id in self.assets],
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_move_unassign_and_reassign_preserve_pick_state(self):
        arrival = create_topic_section(self.db, self.topic, "Arrival", self.assets[:2])
        flowers = create_topic_section(self.db, self.topic, "Flowers", self.assets[2:4])

        self.assertEqual(move_topic_picks(self.db, self.topic, [self.assets[0]], flowers), 1)
        self.assertEqual(move_topic_picks(self.db, self.topic, [self.assets[1]], None), 1)
        state = topic_organise_state(self.db, self.topic)
        self.assertEqual(set(state["pick_ids"]), set(self.assets))
        memberships = {
            row[0]: row[1]
            for row in self.db.execute("SELECT asset_id, section_id FROM topic_section_assets")
        }
        self.assertNotIn(self.assets[0], [row[0] for row in self.db.execute("SELECT asset_id FROM topic_section_assets WHERE section_id=?", (arrival,))])
        self.assertEqual(memberships[self.assets[0]], flowers)
        self.assertNotIn(self.assets[1], memberships)
        self.assertEqual(
            {row[0]: row[1] for row in self.db.execute("SELECT asset_id, decision FROM topic_culling")},
            {asset_id: "pick" for asset_id in self.assets},
        )

    def test_split_merge_reorder_rename_and_delete_are_relationship_only(self):
        first = create_topic_section(self.db, self.topic, "First", self.assets[:3])
        second = create_topic_section(self.db, self.topic, "Second", self.assets[3:5])
        split = split_topic_section(self.db, first, "Portraits", [self.assets[1]])
        rename_topic_section(self.db, split, "Portraits under blossom")
        reorder_topic_sections(self.db, self.topic, [split, second, first])
        self.assertEqual([item["id"] for item in list_topic_sections(self.db, self.topic)], [split, second, first])

        merge_topic_sections(self.db, first, split, "First and portraits")
        self.assertEqual(
            {row[0] for row in self.db.execute("SELECT asset_id FROM topic_section_assets WHERE section_id=?", (first,))},
            set(self.assets[:3]),
        )
        delete_topic_section(self.db, second)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM assets").fetchone()[0], len(self.assets))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM topic_culling WHERE decision='pick'").fetchone()[0], len(self.assets))

    def test_suggestions_apply_as_one_operation_and_require_picks(self):
        created = apply_topic_section_suggestions(self.db, self.topic, [
            {"title": "Morning", "asset_ids": self.assets[:3]},
            {"title": "Garden", "asset_ids": self.assets[3:]},
        ])
        self.assertEqual(len(created), 2)
        self.assertEqual([item["item_count"] for item in list_topic_sections(self.db, self.topic)], [3, 3])
        with self.assertRaises(ValueError):
            apply_topic_section_suggestions(self.db, self.topic, [{"title": "Duplicate", "asset_ids": self.assets[:2]}, {"title": "Duplicate", "asset_ids": self.assets[2:4]}])

    def test_section_builder_static_contract_is_present(self):
        html = (STATIC_ROOT / "organise_picks.html").read_text(encoding="utf-8")
        js = (STATIC_ROOT / "organise_picks.js").read_text(encoding="utf-8")
        for marker in ("Organise Picks", 'id="suggest-sections"', 'id="new-section"', 'id="board-view"', 'id="timeline-view"', 'id="move-selected"'):
            self.assertIn(marker, html)
        for marker in ("unassignedIds", "organise-picks/move", "apply-suggestions", "split", "merge", "draggable", "Pick decisions are unchanged", 'data-photo-action="zoom"', "original_url", "viewer-previous"):
            self.assertIn(marker, js)
        self.assertIn('id="photo-viewer"', html)


if __name__ == "__main__":
    unittest.main()
