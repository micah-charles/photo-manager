from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.backup.android_profiles import (
    finish_android_backup_snapshot,
    list_android_backup_profiles,
    start_android_backup_snapshot,
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
            profile = list_android_backup_profiles(connection)[0]
            self.assertEqual((profile["name"], profile["workers"], profile["destination_status"]), ("Pixel Camera refreshed", 4, "CONNECTED"))
            snapshot_id = start_android_backup_snapshot(connection, profile_id, planned_items=2, planned_bytes=12)
            finish_android_backup_snapshot(connection, snapshot_id, status="COMPLETED", imported_items=1, already_imported_items=1, imported_bytes=12)
            snapshot = connection.execute("SELECT status, imported_items, already_imported_items FROM android_backup_snapshots").fetchone()
            self.assertEqual(tuple(snapshot), ("COMPLETED", 1, 1))
            self.assertIsNotNone(connection.execute("SELECT last_completed_at FROM android_backup_profiles").fetchone()[0])
            connection.close()


if __name__ == "__main__":
    unittest.main()
