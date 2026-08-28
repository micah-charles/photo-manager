from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from photovault.backup.quarantine import build_quarantine_plan, execute_quarantine_plan, undo_quarantine
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test_uuid", "disk", "disk")


class QuarantineTests(unittest.TestCase):
    def setup_catalog(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name) / "photos"
        root.mkdir()
        source = root / "folder" / "photo.jpg"
        source.parent.mkdir()
        source.write_bytes(b"photo")
        db = connect(Path(temp.name) / "catalog.db")
        volume_id = register_volume(db, root, FixedProvider())
        scan_volume(db, volume_id, root)
        return temp, db, source

    def test_quarantine_manifest_journal_and_undo(self) -> None:
        temp, db, source = self.setup_catalog()
        self.addCleanup(temp.cleanup)
        plan = build_quarantine_plan(db, [source], "old duplicate")
        self.assertTrue(source.exists())
        dry = db.execute("SELECT status, dry_run FROM operations WHERE id=?", (plan.operation_id,)).fetchone()
        self.assertEqual(tuple(dry), ("PLANNED", 1))
        result = execute_quarantine_plan(db, plan)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertFalse(source.exists())
        self.assertTrue(plan.items[0].destination_path.exists())
        manifest = json.loads(plan.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["items"][0]["sha256"], plan.items[0].expected_sha256)
        self.assertEqual(db.execute("SELECT result FROM operation_items WHERE operation_id=?", (plan.operation_id,)).fetchone()[0], "QUARANTINED")
        restored = undo_quarantine(db, plan.operation_id)
        self.assertEqual(restored["status"], "COMPLETED")
        self.assertTrue(source.exists())
        self.assertEqual(source.read_bytes(), b"photo")
        self.assertFalse(plan.items[0].destination_path.exists())
        self.assertIsNone(db.execute("SELECT missing_since FROM asset_locations WHERE relative_path='folder/photo.jpg'").fetchone()[0])

    def test_source_changed_before_execute_is_not_moved(self) -> None:
        temp, db, source = self.setup_catalog()
        self.addCleanup(temp.cleanup)
        plan = build_quarantine_plan(db, [source], "test")
        source.write_bytes(b"changed")
        result = execute_quarantine_plan(db, plan)
        self.assertEqual(result["failed"], 1)
        self.assertTrue(source.exists())
        self.assertFalse(plan.items[0].destination_path.exists())

    def test_existing_quarantine_destination_is_conflict(self) -> None:
        temp, db, source = self.setup_catalog()
        self.addCleanup(temp.cleanup)
        plan = build_quarantine_plan(db, [source], "test")
        plan.items[0].destination_path.parent.mkdir(parents=True, exist_ok=True)
        plan.items[0].destination_path.write_bytes(b"different")
        result = execute_quarantine_plan(db, plan)
        self.assertEqual(result["conflicts"], 1)
        self.assertTrue(source.exists())
        self.assertEqual(plan.items[0].destination_path.read_bytes(), b"different")

    def test_undo_does_not_overwrite_recreated_conflicting_original(self) -> None:
        temp, db, source = self.setup_catalog()
        self.addCleanup(temp.cleanup)
        plan = build_quarantine_plan(db, [source], "test")
        self.assertEqual(execute_quarantine_plan(db, plan)["status"], "COMPLETED")
        source.write_bytes(b"different original")
        result = undo_quarantine(db, plan.operation_id)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(source.read_bytes(), b"different original")
        self.assertTrue(plan.items[0].destination_path.exists())


if __name__ == "__main__":
    unittest.main()
