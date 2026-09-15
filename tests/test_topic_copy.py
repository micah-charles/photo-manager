from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.organization import add_assets_to_event, create_event
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.catalog.topic_copy import build_topic_copy_plan, execute_topic_copy
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity
from photovault.web.server import STATIC_ROOT


class FixedProvider:
    def __init__(self, name: str):
        self.name = name

    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test-volume", self.name, self.name)


class TopicCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name) / "source"
        self.destination = Path(self.temp.name) / "destination"
        (self.source / "DCIM" / "Camera").mkdir(parents=True)
        self.destination.mkdir()
        (self.source / "DCIM" / "Camera" / "IMG_0001.JPG").write_bytes(b"jpeg")
        (self.source / "DCIM" / "Camera" / "IMG_0001.NEF").write_bytes(b"raw")
        self.db = connect(Path(self.temp.name) / "catalog.db")
        volume_id = register_volume(self.db, self.source, FixedProvider("Source one"))
        scan_volume(self.db, volume_id, self.source)
        self.topic = create_event(self.db, "Garden trip")
        assets = [row[0] for row in self.db.execute("SELECT id FROM assets ORDER BY id")]
        add_assets_to_event(self.db, self.topic, assets)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_plan_preserves_source_structure_and_can_include_raw(self):
        plan = build_topic_copy_plan(
            self.db,
            self.topic,
            destination_root=str(self.destination),
            folder_name="My garden trip",
            include_raw=True,
        )
        self.assertEqual(len(plan.items), 2)
        self.assertEqual(plan.missing, ())
        self.assertTrue(all(item.destination_path.parts[-4:-1] == ("Source one", "DCIM", "Camera") for item in plan.items))
        visible_plan = build_topic_copy_plan(
            self.db,
            self.topic,
            destination_root=str(self.destination),
            folder_name="Visible only",
            include_raw=False,
        )
        self.assertEqual([item.filename for item in visible_plan.items], ["IMG_0001.JPG"])

    def test_copy_verifies_and_never_overwrites_conflicts(self):
        plan = build_topic_copy_plan(self.db, self.topic, destination_root=str(self.destination))
        first = execute_topic_copy(plan)
        self.assertEqual(first["status"], "COMPLETED")
        self.assertEqual(first["copied"], 2)
        self.assertEqual(first["verified"], 2)
        second = execute_topic_copy(plan)
        self.assertEqual(second["status"], "COMPLETED")
        self.assertEqual(second["copied"], 0)
        self.assertEqual(second["already_present"], 2)

        conflict = plan.items[0].destination_path
        conflict.write_bytes(b"do not replace")
        result = execute_topic_copy(plan)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(conflict.read_bytes(), b"do not replace")

    def test_plan_rejects_source_destination_and_missing_root(self):
        with self.assertRaisesRegex(ValueError, "inside a registered photo source"):
            build_topic_copy_plan(self.db, self.topic, destination_root=str(self.source))
        with self.assertRaisesRegex(ValueError, "must already exist"):
            build_topic_copy_plan(self.db, self.topic, destination_root=str(self.destination / "does-not-exist"))

    def test_topic_workspace_exposes_copy_and_explicit_view_state(self):
        html = (STATIC_ROOT / "topic_workspace.html").read_text(encoding="utf-8")
        js = (STATIC_ROOT / "culling.js").read_text(encoding="utf-8")
        for marker in ('id="copy-topic"', 'id="copy-destination"', 'Include RAW files'):
            self.assertIn(marker, html)
        for marker in ("copy-plan", "/copy`,", "params.get('view')==='picks'", "topic items"):
            self.assertIn(marker, js)


if __name__ == "__main__":
    unittest.main()
