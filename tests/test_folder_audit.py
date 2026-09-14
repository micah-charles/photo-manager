from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.backup.folder_audit import audit_folder
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def __init__(self, value: str):
        self.value = value

    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test_uuid", self.value, self.value)


class FolderAuditTests(unittest.TestCase):
    def setup_catalog(self, old_bytes: bytes, other_bytes: bytes, same_name: bool = True):
        temp = tempfile.TemporaryDirectory()
        old = Path(temp.name) / "old-backup"
        other = Path(temp.name) / "other-disk"
        old.mkdir()
        other.mkdir()
        (old / "photo.jpg").write_bytes(old_bytes)
        (other / ("photo.jpg" if same_name else "copy.jpg")).write_bytes(other_bytes)
        db = connect(Path(temp.name) / "catalog.db")
        self.addCleanup(db.close)
        old_id = register_volume(db, old, FixedProvider("old"))
        other_id = register_volume(db, other, FixedProvider("other"))
        scan_volume(db, old_id, old)
        scan_volume(db, other_id, other)
        return temp, db, old, other_id

    def test_all_files_verified_elsewhere_is_safe_candidate(self) -> None:
        temp, db, old, _ = self.setup_catalog(b"same", b"same")
        self.addCleanup(temp.cleanup)
        self.addCleanup(db.close)
        report = audit_folder(db, old)
        self.assertTrue(report.safe_candidate)
        self.assertEqual(report.verified_elsewhere, 1)
        self.assertEqual(report.unique_files, 0)

    def test_unique_file_is_not_safe(self) -> None:
        temp, db, old, _ = self.setup_catalog(b"old", b"other", same_name=False)
        self.addCleanup(temp.cleanup)
        self.addCleanup(db.close)
        report = audit_folder(db, old)
        self.assertFalse(report.safe_candidate)
        self.assertEqual(report.unique_files, 1)

    def test_same_filename_different_content_is_conflict(self) -> None:
        temp, db, old, _ = self.setup_catalog(b"old", b"other")
        self.addCleanup(temp.cleanup)
        self.addCleanup(db.close)
        report = audit_folder(db, old)
        self.assertEqual(report.conflicts, 1)
        self.assertFalse(report.safe_candidate)

    def test_offline_copy_is_not_claimed_safe(self) -> None:
        temp, db, old, other_id = self.setup_catalog(b"same", b"same")
        self.addCleanup(temp.cleanup)
        self.addCleanup(db.close)
        db.execute("UPDATE volumes SET status='OFFLINE' WHERE id=?", (other_id,))
        db.commit()
        report = audit_folder(db, old)
        self.assertEqual(report.offline_unknown, 1)
        self.assertFalse(report.safe_candidate)

    def test_file_added_after_scan_is_uncatalogued(self) -> None:
        temp, db, old, _ = self.setup_catalog(b"same", b"same")
        self.addCleanup(temp.cleanup)
        self.addCleanup(db.close)
        (old / "new.jpg").write_bytes(b"new")
        report = audit_folder(db, old)
        self.assertEqual(report.uncatalogued, 1)
        self.assertFalse(report.safe_candidate)


if __name__ == "__main__":
    unittest.main()
