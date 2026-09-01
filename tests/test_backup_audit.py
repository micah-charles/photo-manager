from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.backup.audit import audit_backup_set
from photovault.backup.sets import add_member, create_backup_set
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def __init__(self, value: str):
        self.value = value

    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test_uuid", self.value, self.value)


class BackupAuditTests(unittest.TestCase):
    def setup_catalog(self, main_files: dict[str, bytes], backup_files: dict[str, bytes]):
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
        self.addCleanup(db.close)
        main_id = register_volume(db, main, FixedProvider("main"))
        backup_id = register_volume(db, backup, FixedProvider("backup"))
        scan_volume(db, main_id, main)
        scan_volume(db, backup_id, backup)
        set_id = create_backup_set(db, "Family", required_copies=2)
        add_member(db, set_id, main_id, "PRIMARY")
        add_member(db, set_id, backup_id, "BACKUP")
        return temp, db, set_id

    def test_protected_and_missing_backup(self) -> None:
        temp, db, set_id = self.setup_catalog({"kept.jpg": b"kept", "missing.jpg": b"missing"}, {"kept.jpg": b"kept"})
        self.addCleanup(temp.cleanup)
        self.addCleanup(db.close)
        report = audit_backup_set(db, set_id)
        self.assertEqual(report.counts["VERIFIED_REDUNDANT"], 1)
        self.assertEqual(report.counts["MISSING_BACKUP"], 1)
        self.assertEqual(report.protection_percent, 50.0)

    def test_backup_only(self) -> None:
        temp, db, set_id = self.setup_catalog({"main.jpg": b"main"}, {"main.jpg": b"main", "old.jpg": b"old"})
        self.addCleanup(temp.cleanup)
        self.addCleanup(db.close)
        report = audit_backup_set(db, set_id)
        self.assertEqual(report.counts["BACKUP_ONLY"], 1)

    def test_same_path_different_content_is_conflict(self) -> None:
        temp, db, set_id = self.setup_catalog({"same.jpg": b"main"}, {"same.jpg": b"backup"})
        self.addCleanup(temp.cleanup)
        self.addCleanup(db.close)
        report = audit_backup_set(db, set_id)
        self.assertEqual(report.counts["CONFLICT"], 2)

    def test_offline_required_volume_is_unknown(self) -> None:
        temp, db, set_id = self.setup_catalog({"same.jpg": b"same"}, {"same.jpg": b"same"})
        self.addCleanup(temp.cleanup)
        self.addCleanup(db.close)
        db.execute("UPDATE volumes SET status='OFFLINE' WHERE display_name='backup'")
        db.commit()
        report = audit_backup_set(db, set_id)
        self.assertEqual(report.counts["OFFLINE_UNKNOWN"], 1)

    def test_primary_only_is_unprotected_when_no_backup_member_exists(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name) / "main"
        root.mkdir()
        (root / "only.jpg").write_bytes(b"only")
        db = connect(Path(temp.name) / "catalog.db")
        self.addCleanup(db.close)
        volume_id = register_volume(db, root, FixedProvider("main"))
        scan_volume(db, volume_id, root)
        set_id = create_backup_set(db, "Unprotected", required_copies=2)
        add_member(db, set_id, volume_id, "PRIMARY")
        report = audit_backup_set(db, set_id)
        self.assertEqual(report.counts["UNPROTECTED"], 1)


if __name__ == "__main__":
    unittest.main()
