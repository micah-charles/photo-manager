from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from photovault.backup.source_import import SourceImportItem, stream_source_to_file
from photovault.sources.base import SourceIdentity


class FakeSource:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def stream_object(self, object_id: str, sink) -> dict[str, int | float]:
        for offset in range(0, len(self.payload), 3):
            sink.write(self.payload[offset : offset + 3])
        return {"bytes_received": len(self.payload), "bytes_per_second": 100.0, "elapsed_seconds": 0.01}


class SourceImportTests(unittest.TestCase):
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
