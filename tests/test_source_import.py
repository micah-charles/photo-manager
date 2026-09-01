from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from photovault.backup.source_import import (
    SourceImportItem,
    SourceImportStatus,
    import_source_item,
    import_source_items,
    plan_source_import,
    restore_import_modified_times,
    stream_source_to_file,
)
from photovault.catalog.sources import record_source_items, register_source
from photovault.database.connection import connect
from photovault.sources.base import PhotoItem, SourceIdentity


class FakeSource:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def stream_object(self, object_id: str, sink) -> dict[str, int | float]:
        for offset in range(0, len(self.payload), 3):
            sink.write(self.payload[offset : offset + 3])
        return {"bytes_received": len(self.payload), "bytes_per_second": 100.0, "elapsed_seconds": 0.01}

    def identity(self):
        return SourceIdentity("android_test", "Google", "Pixel 8 Pro", "Pixel 8 Pro", "test")


class InterruptibleRangeSource(FakeSource):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.fail_once = True
        self.offsets: list[int] = []

    def capabilities(self):
        return frozenset({"range_read"})

    def stream_object(self, object_id: str, sink, *, offset: int = 0) -> dict[str, int | float]:
        self.offsets.append(offset)
        remainder = self.payload[offset:]
        if self.fail_once:
            self.fail_once = False
            sink.write(remainder[:5])
            raise ConnectionError("simulated Wi-Fi interruption")
        for position in range(0, len(remainder), 3):
            sink.write(remainder[position : position + 3])
        return {"bytes_received": len(remainder), "bytes_per_second": 100.0, "elapsed_seconds": 0.01}


class SourceImportTests(unittest.TestCase):
    def test_source_identity_and_inventory_are_persisted_separately(self) -> None:
        identity = SourceIdentity("android_test", "Google", "Pixel 8 Pro", "Pixel 8 Pro", "test", 0x18D1, 0x4EE1)
        item = PhotoItem("android_test", "675", "28", "photo.jpg", "IMAGE", 123)
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "catalog.db")
            register_source(connection, identity)
            self.assertEqual(record_source_items(connection, identity.source_id, [item], "DCIM/Camera"), 1)
            profile = connection.execute("SELECT source_id, model, usb_vendor_id FROM source_profiles").fetchone()
            stored_item = connection.execute("SELECT object_id, logical_path, size_bytes FROM source_items").fetchone()
            self.assertEqual(tuple(profile), ("android_test", "Pixel 8 Pro", 0x18D1))
            self.assertEqual(tuple(stored_item), ("675", "DCIM/Camera/photo.jpg", 123))
            self.assertNotIn("serial", {row[1] for row in connection.execute("PRAGMA table_info(source_profiles)")})
            connection.close()

    def test_stream_is_hashed_and_renamed_atomically(self) -> None:
        payload = b"bounded source payload"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = stream_source_to_file(
                FakeSource(payload),
                SourceImportItem("675", "DCIM/Camera/photo.jpg", len(payload), hashlib.sha256(payload).hexdigest()),
                root,
            )
            destination = root / "DCIM/Camera/photo.jpg"
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(result["bytes_written"], len(payload))
            self.assertFalse((root / "DCIM/Camera/photo.jpg.photomanager-partial").exists())

    def test_import_records_verified_location_and_operation(self) -> None:
        payload = b"catalogued Android object"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = connect(root / "catalog.db")
            self.addCleanup(connection.close)
            register_source(connection, SourceIdentity("android_test", "Google", "Pixel 8 Pro", "Pixel 8 Pro", "test"))
            connection.execute(
                "INSERT INTO volumes(id, display_name, identity_kind, identity_value, first_seen, last_seen, status) VALUES ('vol_dest', 'Destination', 'test', 'dest', datetime('now'), datetime('now'), 'CONNECTED')"
            )
            connection.commit()
            result = import_source_item(connection, FakeSource(payload), SourceImportItem("675", "DCIM/Camera/photo.jpg", len(payload), media_type="IMAGE"), root / "destination", "vol_dest")
            self.assertTrue((root / "destination/DCIM/Camera/photo.jpg").exists())
            self.assertEqual(result["bytes_written"], len(payload))
            self.assertEqual(connection.execute("SELECT status FROM operations WHERE id=?", (result["operation_id"],)).fetchone()[0], "COMPLETED")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM verification_history WHERE result='VERIFIED'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM asset_locations WHERE volume_id='vol_dest'").fetchone()[0], 1)
            connection.close()

    def test_import_indexes_metadata_after_verified_publish(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")
        from io import BytesIO

        image = Image.new("RGB", (17, 11), (20, 40, 60))
        payload_buffer = BytesIO()
        image.save(payload_buffer, format="JPEG")
        payload = payload_buffer.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = connect(root / "catalog.db")
            self.addCleanup(connection.close)
            connection.execute(
                "INSERT INTO volumes(id, display_name, identity_kind, identity_value, first_seen, last_seen, status) VALUES ('vol_dest', 'Destination', 'test', 'dest', datetime('now'), datetime('now'), 'CONNECTED')"
            )
            connection.commit()
            result = import_source_item(
                connection, FakeSource(payload),
                SourceImportItem("675", "DCIM/Camera/photo.jpg", len(payload), media_type="IMAGE"),
                root / "destination", "vol_dest",
            )
            asset_id = result["asset_id"]
            metadata = connection.execute(
                "SELECT width, height FROM media_metadata WHERE asset_id=?", (asset_id,)
            ).fetchone()
            self.assertEqual(tuple(metadata), (17, 11))
            connection.close()


    def test_import_preserves_source_modified_time_when_supported(self) -> None:
        payload = b"metadata is in the original bytes"
        modified = datetime(2023, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = stream_source_to_file(
                FakeSource(payload),
                SourceImportItem("675", "DCIM/Camera/photo.jpg", len(payload), modified_at=modified),
                root,
            )
            self.assertEqual(Path(result["destination"]).stat().st_mtime_ns // 1_000_000_000, int(modified.timestamp()))

    def test_restore_import_modified_times_repairs_existing_verified_import(self) -> None:
        payload = b"original"
        modified = datetime(2021, 7, 8, 9, 10, 11, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = connect(root / "catalog.db")
            self.addCleanup(connection.close)
            connection.execute("INSERT INTO volumes(id, display_name, identity_kind, identity_value, first_seen, last_seen, status) VALUES ('vol_dest', 'Destination', 'test', 'dest', datetime('now'), datetime('now'), 'CONNECTED')")
            connection.commit()
            import_source_item(connection, FakeSource(payload), SourceImportItem("1", "DCIM/Camera/a.jpg", len(payload), modified_at=modified), root, "vol_dest")
            destination = root / "DCIM/Camera/a.jpg"; destination.touch()
            restored = restore_import_modified_times(connection, root, "vol_dest")
            self.assertEqual(restored["restored"], 1)
            self.assertEqual(destination.stat().st_mtime_ns // 1_000_000_000, int(modified.timestamp()))
            connection.close()

    def test_mismatch_removes_partial_and_never_publishes_final(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                stream_source_to_file(FakeSource(b"actual"), SourceImportItem("1", "photo.jpg", 99), root)
            self.assertFalse((root / "photo.jpg").exists())
            self.assertFalse((root / "photo.jpg.photomanager-partial").exists())

    def test_range_capable_source_resumes_retained_partial_after_interruption(self) -> None:
        payload = b"resume without re-downloading verified prefix"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = InterruptibleRangeSource(payload)
            item = SourceImportItem("1", "photo.jpg", len(payload), hashlib.sha256(payload).hexdigest())
            with self.assertRaisesRegex(ConnectionError, "interruption"):
                stream_source_to_file(source, item, root)
            partial = root / "photo.jpg.photomanager-partial"
            self.assertEqual(partial.read_bytes(), payload[:5])
            result = stream_source_to_file(source, item, root)
            self.assertEqual((root / "photo.jpg").read_bytes(), payload)
            self.assertFalse(partial.exists())
            self.assertEqual(source.offsets, [0, 5])
            self.assertEqual(result["resumed_bytes"], 5)

    def test_batch_import_retries_transient_range_source_failure(self) -> None:
        payload = b"retry from retained prefix"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = connect(root / "catalog.db")
            connection.execute("INSERT INTO volumes(id, display_name, identity_kind, identity_value, first_seen, last_seen, status) VALUES ('vol_dest', 'Destination', 'test', 'dest', datetime('now'), datetime('now'), 'CONNECTED')")
            connection.commit()
            source = InterruptibleRangeSource(payload)
            retries: list[tuple[str, int]] = []
            result = import_source_items(
                connection, source, [SourceImportItem("1", "photo.jpg", len(payload))], root, "vol_dest",
                retry_attempts=1, retry_base_delay_seconds=0,
                retry_callback=lambda item, attempt, exc: retries.append((item.object_id, attempt)),
            )
            self.assertEqual((result["imported"], retries, source.offsets), (1, [("1", 1)], [0, 5]))
            self.assertEqual((root / "photo.jpg").read_bytes(), payload)
            connection.close()

    def test_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                stream_source_to_file(FakeSource(b"x"), SourceImportItem("1", "../outside.jpg", 1), Path(directory))

    def test_incremental_plan_recognizes_completed_source_item(self) -> None:
        payload = b"incremental payload"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = connect(root / "catalog.db")
            connection.execute(
                "INSERT INTO volumes(id, display_name, identity_kind, identity_value, first_seen, last_seen, status) VALUES ('vol_dest', 'Destination', 'test', 'dest', datetime('now'), datetime('now'), 'CONNECTED')"
            )
            connection.commit()
            item = SourceImportItem("675", "DCIM/Camera/photo.jpg", len(payload), media_type="IMAGE")
            import_source_item(connection, FakeSource(payload), item, root / "destination", "vol_dest")
            plan = plan_source_import(connection, FakeSource(payload), [item], root / "destination", "vol_dest")
            self.assertEqual(plan[0].status, SourceImportStatus.ALREADY_IMPORTED)
            connection.close()

    def test_batch_import_skips_completed_and_imports_new_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = connect(root / "catalog.db")
            connection.execute(
                "INSERT INTO volumes(id, display_name, identity_kind, identity_value, first_seen, last_seen, status) VALUES ('vol_dest', 'Destination', 'test', 'dest', datetime('now'), datetime('now'), 'CONNECTED')"
            )
            connection.commit()
            source = FakeSource(b"batch payload")
            first = SourceImportItem("1", "DCIM/Camera/a.jpg", len(source.payload))
            import_source_item(connection, source, first, root / "destination", "vol_dest")
            second = SourceImportItem("2", "DCIM/Camera/b.jpg", len(source.payload))
            result = import_source_items(connection, source, [first, second], root / "destination", "vol_dest", fsync_mode="batch", batch_files=1)
            self.assertEqual((result["planned"], result["imported"], result["already_imported"]), (2, 1, 1))
            self.assertTrue((root / "destination/DCIM/Camera/b.jpg").exists())
            connection.close()


if __name__ == "__main__":
    unittest.main()
