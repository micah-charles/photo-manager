from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from photovault.backup.reconcile import reconcile_backup_set
from photovault.backup.sets import add_member, create_backup_set
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def __init__(self, value: str):
        self.value = value

    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test_uuid", self.value, self.value)


class ReconciliationTests(unittest.TestCase):
    def build(self, main_files: dict[str, bytes], backup_files: dict[str, bytes]):
        temp = tempfile.TemporaryDirectory()
        main = Path(temp.name) / "main"
        backup = Path(temp.name) / "backup"
        main.mkdir()
        backup.mkdir()
        for name, content in main_files.items():
            (main / name).parent.mkdir(parents=True, exist_ok=True)
            (main / name).write_bytes(content)
        for name, content in backup_files.items():
            (backup / name).parent.mkdir(parents=True, exist_ok=True)
            (backup / name).write_bytes(content)
        db = connect(Path(temp.name) / "catalog.db")
        main_id = register_volume(db, main, FixedProvider("main"))
        backup_id = register_volume(db, backup, FixedProvider("backup"))
        scan_volume(db, main_id, main)
        scan_volume(db, backup_id, backup)
        set_id = create_backup_set(db, "Family")
        add_member(db, set_id, main_id, "PRIMARY")
        add_member(db, set_id, backup_id, "BACKUP")
        return temp, db, set_id, backup_id

    def test_reconciles_verified_renamed_main_only_and_backup_only(self) -> None:
        temp, db, set_id, _ = self.build(
            {"same.jpg": b"same", "main-only.jpg": b"main", "renamed.jpg": b"rename"},
            {"same.jpg": b"same", "backup-only.jpg": b"backup", "renamed-copy.jpg": b"rename"},
        )
        self.addCleanup(temp.cleanup)
        report = reconcile_backup_set(db, set_id)
        self.assertEqual(report.counts["VERIFIED"], 2)
        self.assertEqual(report.counts["MAIN_ONLY"], 1)
        self.assertEqual(report.counts["BACKUP_ONLY"], 1)

    def test_conflict_is_reported_for_same_path_different_hash(self) -> None:
        temp, db, set_id, _ = self.build({"same.jpg": b"main"}, {"same.jpg": b"backup"})
        self.addCleanup(temp.cleanup)
        report = reconcile_backup_set(db, set_id)
        self.assertEqual(report.counts["CONFLICT"], 1)

    def test_offline_pair_is_unknown_and_csv_is_exported(self) -> None:
        temp, db, set_id, backup_id = self.build({"same.jpg": b"same"}, {"same.jpg": b"same"})
        self.addCleanup(temp.cleanup)
        db.execute("UPDATE volumes SET status='OFFLINE' WHERE id=?", (backup_id,))
        db.commit()
        report = reconcile_backup_set(db, set_id)
        self.assertEqual(report.counts["UNKNOWN_OFFLINE"], 1)
        output = Path(temp.name) / "reconciliation.csv"
        report.write_csv(output)
        with output.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["status"], "UNKNOWN_OFFLINE")


if __name__ == "__main__":
    unittest.main()
