from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.backup.android_profiles import (
    finish_android_backup_snapshot,
    get_android_backup_profile,
    list_android_backup_profiles,
    list_android_backup_snapshots,
    start_android_backup_snapshot,
    profile_folders,
    missing_from_source,
    upsert_android_backup_profile,
)
from photovault.catalog.sources import register_source
from photovault.catalog.scanner import register_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity
from photovault.sources.base import SourceIdentity


class FixedVolumeProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test_volume", "destination-disk", "Destination disk")


class AndroidBackupProfileTests(unittest.TestCase):
    def test_profile_is_keyed_by_persistent_source_and_volume_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "destination"; destination.mkdir()
            connection = connect(root / "catalog.db")
            identity = SourceIdentity("android_wifi_persistent", "Google", "Pixel", "Pixel", "android_companion_wifi")
            register_source(connection, identity)
            volume_id = register_volume(connection, destination, FixedVolumeProvider())
            profile_id = upsert_android_backup_profile(
                connection, source_id=identity.source_id, name="Pixel Camera", folder_path="DCIM/Camera",
                media_filter="ALL", destination_volume_id=volume_id, workers=5,
            )
            same_id = upsert_android_backup_profile(
                connection, source_id=identity.source_id, name="Pixel Camera refreshed", folder_path="DCIM/Camera/",
                media_filter="ALL", destination_volume_id=volume_id, workers=4,
            )
            self.assertEqual(profile_id, same_id)
            self.assertEqual(profile_folders(connection, profile_id), ("DCIM/Camera",))
            profile = list_android_backup_profiles(connection)[0]
            self.assertEqual((profile["name"], profile["workers"], profile["destination_status"]), ("Pixel Camera refreshed", 4, "CONNECTED"))
            snapshot_id = start_android_backup_snapshot(connection, profile_id, planned_items=2, planned_bytes=12)
            finish_android_backup_snapshot(connection, snapshot_id, status="COMPLETED", imported_items=1, already_imported_items=1, imported_bytes=12)
            snapshot = connection.execute("SELECT status, imported_items, already_imported_items FROM android_backup_snapshots").fetchone()
            self.assertEqual(tuple(snapshot), ("COMPLETED", 1, 1))
            self.assertIsNotNone(connection.execute("SELECT last_completed_at FROM android_backup_profiles").fetchone()[0])
            loaded = get_android_backup_profile(connection, profile_id)
            self.assertEqual((loaded["id"], loaded["destination_status"], loaded["destination_mount_path"]), (profile_id, "CONNECTED", str(destination.resolve())))
            history = list_android_backup_snapshots(connection, profile_id=profile_id)
            self.assertEqual((len(history), history[0]["profile_name"], history[0]["status"]), (1, "Pixel Camera refreshed", "COMPLETED"))
            connection.close()

    def test_profile_persists_multiple_selected_folders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); destination = root / "destination"; destination.mkdir()
            connection = connect(root / "catalog.db")
            identity = SourceIdentity("android_wifi_persistent", "Google", "Pixel", "Pixel", "android_companion_wifi")
            register_source(connection, identity)
            volume_id = register_volume(connection, destination, FixedVolumeProvider())
            profile_id = upsert_android_backup_profile(
                connection, source_id=identity.source_id, name="Pixel media", folder_paths=("Pictures", "DCIM/Camera", "Pictures/"),
                media_filter="ALL", destination_volume_id=volume_id,
            )
            self.assertEqual(profile_folders(connection, profile_id), ("DCIM/Camera", "Pictures"))
            self.assertEqual(connection.execute("SELECT folder_path FROM android_backup_profiles").fetchone()[0], "DCIM/Camera|Pictures")
            connection.close()

    def test_missing_source_items_are_informational_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); destination = root / "destination"; destination.mkdir()
            connection = connect(root / "catalog.db")
            identity = SourceIdentity("android_wifi_persistent", "Google", "Pixel", "Pixel", "android_companion_wifi")
            register_source(connection, identity)
            volume_id = register_volume(connection, destination, FixedVolumeProvider())
            connection.execute("INSERT INTO operations(id, operation_type, created_at, status, dry_run, details_json) VALUES ('op_test', 'IMPORT', datetime('now'), 'COMPLETED', 0, '{}')")
            connection.execute(
                """INSERT INTO source_imports(source_id, logical_path, source_object_id, destination_volume_id,
                   destination_relative_path, sha256, operation_id, imported_at)
                   VALUES (?, 'DCIM/Camera/old.jpg', '1', ?, 'DCIM/Camera/old.jpg', 'abc', 'op_test', datetime('now'))""",
                (identity.source_id, volume_id),
            )
            connection.commit()
            missing = missing_from_source(
                connection, source_id=identity.source_id, destination_volume_id=volume_id,
                folders=("DCIM/Camera",), current_logical_paths=("DCIM/Camera/new.jpg",),
            )
            self.assertEqual(missing, ("DCIM/Camera/old.jpg",))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM source_imports").fetchone()[0], 1)
            connection.close()


if __name__ == "__main__":
    unittest.main()
