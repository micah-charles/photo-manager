from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.backup.audit import audit_backup_set
from photovault.backup.copy import build_copy_plan, execute_copy_plan
from photovault.backup.sets import add_member, create_backup_set
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def __init__(self, value: str):
        self.value = value

    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test_uuid", self.value, self.value)


class CopyPlanTests(unittest.TestCase):
    def setup_missing_backup(self):
        temp = tempfile.TemporaryDirectory()
        main = Path(temp.name) / "main"
        backup = Path(temp.name) / "backup"
        main.mkdir()
        backup.mkdir()
        (main / "missing.jpg").write_bytes(b"important")
        db = connect(Path(temp.name) / "catalog.db")
        main_id = register_volume(db, main, FixedProvider("main"))
        backup_id = register_volume(db, backup, FixedProvider("backup"))
        scan_volume(db, main_id, main)
        scan_volume(db, backup_id, backup)
        set_id = create_backup_set(db, "Family")
        add_member(db, set_id, main_id, "PRIMARY")
        add_member(db, set_id, backup_id, "BACKUP")
        return temp, db, set_id

    def test_dry_run_creates_plan_and_changes_no_media(self) -> None:
        temp, db, set_id = self.setup_missing_backup()
        self.addCleanup(temp.cleanup)
        plan = build_copy_plan(db, set_id)
        self.assertEqual(len(plan.items), 1)
        self.assertFalse(plan.items[0].destination_path.exists())
        journal = db.execute("SELECT status, dry_run FROM operations WHERE id=?", (plan.operation_id,)).fetchone()
        self.assertEqual(tuple(journal), ("PLANNED", 1))

    def test_copy_reads_destination_and_catalogues_only_verified_result(self) -> None:
        temp, db, set_id = self.setup_missing_backup()
        self.addCleanup(temp.cleanup)
        plan = build_copy_plan(db, set_id)
        result = execute_copy_plan(db, plan)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["verified"], 1)
        self.assertEqual(plan.items[0].destination_path.read_bytes(), b"important")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM verification_history WHERE result='VERIFIED'").fetchone()[0], 1)
        self.assertEqual(audit_backup_set(db, set_id).counts["VERIFIED_REDUNDANT"], 1)

    def test_corrupt_destination_fails_verification_and_is_not_catalogued(self) -> None:
        temp, db, set_id = self.setup_missing_backup()
        self.addCleanup(temp.cleanup)
        plan = build_copy_plan(db, set_id)

        def corrupt_copy(source: str, destination: str):
            Path(destination).write_bytes(b"corrupt")

        result = execute_copy_plan(db, plan, copy_fn=corrupt_copy)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failed"], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM verification_history WHERE result='FAILED'").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM asset_locations WHERE volume_id=? AND missing_since IS NULL", (plan.backup_volume_id,)).fetchone()[0], 0)

    def test_existing_different_destination_is_never_overwritten(self) -> None:
        temp, db, set_id = self.setup_missing_backup()
        self.addCleanup(temp.cleanup)
        plan = build_copy_plan(db, set_id)
        plan.items[0].destination_path.parent.mkdir(parents=True, exist_ok=True)
        plan.items[0].destination_path.write_bytes(b"different")
        result = execute_copy_plan(db, plan)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(plan.items[0].destination_path.read_bytes(), b"different")
        item = db.execute("SELECT result, verification_result FROM operation_items WHERE operation_id=?", (plan.operation_id,)).fetchone()
        self.assertEqual(tuple(item), ("CONFLICT", "NOT_VERIFIED"))

    def test_existing_identical_destination_is_catalogued_as_verified(self) -> None:
        temp, db, set_id = self.setup_missing_backup()
        self.addCleanup(temp.cleanup)
        plan = build_copy_plan(db, set_id)
        destination = plan.items[0].destination_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"important")
        result = execute_copy_plan(db, plan)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["copied"], 0)
        self.assertEqual(result["verified"], 1)
        self.assertEqual(
            db.execute(
                "SELECT COUNT(*) FROM asset_locations WHERE volume_id=? AND relative_path=? AND missing_since IS NULL",
                (plan.backup_volume_id, plan.items[0].relative_path),
            ).fetchone()[0],
            1,
        )
        self.assertEqual(db.execute("SELECT COUNT(*) FROM verification_history WHERE result='VERIFIED'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
