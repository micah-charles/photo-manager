from __future__ import annotations

import sqlite3
import tempfile
import unittest
import plistlib
from pathlib import Path

from photovault.catalog.scanner import register_volume, scan_volume
from photovault.catalog.volume_state import refresh_volume_statuses
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity
from photovault.platform.macos.volume import MacOSVolumeProvider


class FixedVolumeProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test_uuid", "disk-123", "Test Disk", "TESTFS", 1234)


class CatalogPhase1Tests(unittest.TestCase):
    def test_in_memory_catalog_does_not_create_a_filesystem_artifact(self) -> None:
        db = connect(":memory:")
        self.addCleanup(db.close)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 11)

    def test_register_scan_and_rescan_are_read_only_and_incremental(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "photos"
            root.mkdir()
            (root / "one.jpg").write_bytes(b"one")
            (root / "notes.txt").write_text("ignored", encoding="utf-8")
            catalog = Path(temp) / "catalog.db"
            db = connect(catalog)

            volume_id = register_volume(db, root)
            first = scan_volume(db, volume_id, root)
            self.assertEqual(first["files_catalogued"], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM asset_locations").fetchone()[0], 1)

            second = scan_volume(db, volume_id, root)
            self.assertEqual(second["files_catalogued"], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 1)

            (root / "one.jpg").unlink()
            scan_volume(db, volume_id, root)
            missing = db.execute(
                "SELECT missing_since FROM asset_locations WHERE relative_path='one.jpg'"
            ).fetchone()[0]
            self.assertIsNotNone(missing)

    def test_catalog_survives_when_volume_is_not_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "disk"
            root.mkdir()
            (root / "photo.heic").write_bytes(b"image")
            db = connect(Path(temp) / "catalog.db")
            volume_id = register_volume(db, root)
            scan_volume(db, volume_id, root)
            db.close()

            reopened = connect(Path(temp) / "catalog.db")
            row = reopened.execute(
                "SELECT filename, size_bytes FROM asset_locations WHERE volume_id=?", (volume_id,)
            ).fetchone()
            self.assertEqual((row[0], row[1]), ("photo.heic", 5))

    def test_refresh_marks_missing_mount_offline_without_erasing_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "disk"
            root.mkdir()
            (root / "photo.jpg").write_bytes(b"image")
            db = connect(Path(temp) / "catalog.db")
            volume_id = register_volume(db, root)
            scan_volume(db, volume_id, root)
            (root / "photo.jpg").unlink()
            root.rmdir()
            self.assertEqual(refresh_volume_statuses(db)["offline"], 1)
            self.assertEqual(db.execute("SELECT status FROM volumes WHERE id=?", (volume_id,)).fetchone()[0], "OFFLINE")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 1)

    def test_byte_identical_files_become_one_asset_with_two_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "disk"
            (root / "a").mkdir(parents=True)
            (root / "b").mkdir()
            content = b"same photo bytes"
            (root / "a" / "photo.jpg").write_bytes(content)
            (root / "b" / "copy.jpg").write_bytes(content)
            db = connect(Path(temp) / "catalog.db")
            volume_id = register_volume(db, root)
            scan_volume(db, volume_id, root)
            assets = db.execute("SELECT id FROM assets").fetchall()
            locations = db.execute(
                "SELECT asset_id, relative_path FROM asset_locations ORDER BY relative_path"
            ).fetchall()
            self.assertEqual(len(assets), 1)
            self.assertEqual(len(db.execute("SELECT * FROM exact_hashes").fetchall()), 1)
            self.assertEqual({row[0] for row in locations}, {assets[0][0]})
            self.assertEqual([row[1] for row in locations], ["a/photo.jpg", "b/copy.jpg"])

    def test_rename_preserves_asset_identity_and_changed_bytes_get_new_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "disk"
            root.mkdir()
            original = root / "original.jpg"
            renamed = root / "renamed.jpg"
            original.write_bytes(b"original")
            db = connect(Path(temp) / "catalog.db")
            volume_id = register_volume(db, root)
            scan_volume(db, volume_id, root)
            asset_before = db.execute("SELECT asset_id FROM asset_locations").fetchone()[0]
            original.rename(renamed)
            scan_volume(db, volume_id, root)
            asset_after = db.execute(
                "SELECT asset_id FROM asset_locations WHERE relative_path='renamed.jpg'"
            ).fetchone()[0]
            self.assertEqual(asset_before, asset_after)
            self.assertIsNotNone(db.execute(
                "SELECT missing_since FROM asset_locations WHERE relative_path='original.jpg'"
            ).fetchone()[0])

            renamed.write_bytes(b"changed")
            scan_volume(db, volume_id, root)
            changed_asset = db.execute(
                "SELECT asset_id FROM asset_locations WHERE relative_path='renamed.jpg'"
            ).fetchone()[0]
            self.assertNotEqual(asset_before, changed_asset)
            # The old content remains catalogued at its historical missing path;
            # the replaced path is now a different logical asset.
            self.assertEqual(db.execute("SELECT COUNT(*) FROM exact_hashes").fetchone()[0], 2)

    def test_same_stable_volume_identity_survives_remount_at_new_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first_root = Path(temp) / "mount-a"
            second_root = Path(temp) / "mount-b"
            first_root.mkdir()
            second_root.mkdir()
            (first_root / "a.jpg").write_bytes(b"a")
            (second_root / "b.jpg").write_bytes(b"b")
            db = connect(Path(temp) / "catalog.db")
            provider = FixedVolumeProvider()
            volume_id = register_volume(db, first_root, provider)
            scan_volume(db, volume_id, first_root)
            remounted_id = register_volume(db, second_root, provider)
            self.assertEqual(volume_id, remounted_id)
            self.assertEqual(
                db.execute("SELECT current_mount_path FROM volumes WHERE id=?", (volume_id,)).fetchone()[0],
                str(second_root.resolve()),
            )
            scan_volume(db, remounted_id, second_root)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM volumes").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM asset_locations").fetchone()[0], 2)

    def test_macos_provider_reads_volume_uuid_without_core_logic_dependency(self) -> None:
        payload = plistlib.dumps({
            "VolumeUUID": "ABC-123",
            "VolumeName": "Photos",
            "FileSystemPersonality": "APFS",
            "TotalSize": 500,
        })

        def fake_runner(*args, **kwargs):
            class Result:
                stdout = payload
            return Result()

        identity = MacOSVolumeProvider(runner=fake_runner).identify(Path(tempfile.gettempdir()))
        self.assertEqual(identity.identity_kind, "macos_volume_uuid")
        self.assertEqual(identity.identity_value, "abc-123")
        self.assertEqual(identity.capacity_bytes, 500)


if __name__ == "__main__":
    unittest.main()
