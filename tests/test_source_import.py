from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from photovault.backup.source_import import SourceImportItem, stream_source_to_file
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

    def test_mismatch_removes_partial_and_never_publishes_final(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                stream_source_to_file(FakeSource(b"actual"), SourceImportItem("1", "photo.jpg", 99), root)
            self.assertFalse((root / "photo.jpg").exists())
            self.assertFalse((root / "photo.jpg.photomanager-partial").exists())

    def test_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                stream_source_to_file(FakeSource(b"x"), SourceImportItem("1", "../outside.jpg", 1), Path(directory))


if __name__ == "__main__":
    unittest.main()
