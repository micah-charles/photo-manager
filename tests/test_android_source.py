from __future__ import annotations

import unittest
from datetime import datetime

from pathlib import Path
from unittest.mock import patch

from photovault.sources.android import AndroidMacMtpSource, JsonLineBridge, stream_test_folder
from photovault.sources.base import SourceIdentity, SourceStorage


class FakeBridge:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []

    def request(self, operation: str, **arguments):
        self.requests.append((operation, arguments))
        if operation == "list_storages":
            return {"ok": True, "storages": [{"storage_id": 65537, "name": "Internal storage", "capacity_bytes": 10, "free_bytes": 5}]}
        if operation == "list_children":
            return {"ok": True, "items": [{"object_id": 28, "parent_id": 10, "name": "Camera", "format": 0x3001}], "total": 1, "next_offset": None}
        if operation == "find_child":
            return {"ok": True, "item": {"object_id": 28, "parent_id": 10, "name": "Camera", "format": 0x3001}}
        if operation == "object_info":
            return {"ok": True, "item": {"object_id": 675, "parent_id": 28, "name": "photo.jpg", "format": 0x3801, "size_bytes": 123, "created_at": "20260828T120000", "modified_at": "20260828T120100"}}
        raise AssertionError(operation)


class AndroidSourceTests(unittest.TestCase):
    @patch("photovault.sources.android.platform.system", return_value="Darwin")
    def test_atomic_stream_test_verifies_native_byte_count(self, _system) -> None:
        class Reader:
            def __init__(self, chunks):
                self.chunks = iter(chunks)

            def read(self, _size=-1):
                return next(self.chunks, b"")

            def close(self):
                pass

        class Process:
            stdout = Reader([b"abc", b"def"])
            stderr = Reader([b"PHOTOVAULT_STREAM_RESULT\t6\t6\n"])

            def wait(self, timeout):
                return 0

        class Sink:
            data = bytearray()

            def write(self, chunk):
                self.data.extend(chunk)

        sink = Sink()
        helper = Path(__file__)
        metrics = stream_test_folder(helper, "DCIM/Camera", sink, runner=lambda *args, **kwargs: Process())

        self.assertEqual(bytes(sink.data), b"abcdef")
        self.assertEqual(metrics["bytes_received"], 6)

    def test_normalizes_storage_and_object_metadata(self) -> None:
        bridge = FakeBridge()
        identity = SourceIdentity("android_test", "Google", "Pixel 8 Pro", "Pixel 8 Pro", "test")
        source = AndroidMacMtpSource(bridge, identity)

        storage = list(source.list_storages())[0]
        camera = list(source.list_children("10"))[0]
        photo = source.stat_item("675")

        self.assertEqual(storage.storage_id, 65537)
        self.assertTrue(camera.is_collection)
        self.assertEqual(photo.media_type, "IMAGE")
        self.assertEqual(photo.size_bytes, 123)
        self.assertEqual(photo.created_at, datetime(2026, 8, 28, 12, 0))
        self.assertEqual(bridge.requests[1], ("list_children", {"parent_id": 10, "offset": 0, "limit": 50}))

    def test_cached_storages_and_lazy_folder_lookup_preserve_session_sequence(self) -> None:
        bridge = FakeBridge()
        identity = SourceIdentity("android_test", "Google", "Pixel 8 Pro", "Pixel 8 Pro", "test")
        storage = SourceStorage(65537, "Internal storage", 10, 5)
        source = AndroidMacMtpSource(bridge, identity, _storages=(storage,))

        self.assertEqual(list(source.list_storages()), [storage])
        camera = source.find_child("10", "Camera")

        self.assertIsNotNone(camera)
        self.assertEqual(camera.object_id, "28")
        self.assertEqual(bridge.requests, [("find_child", {"parent_id": 10, "name": "Camera"})])

    def test_list_children_page_forwards_bounds(self) -> None:
        bridge = FakeBridge()
        source = AndroidMacMtpSource(bridge, SourceIdentity("id", "Google", "Pixel", "Pixel", "test"))

        items, total, next_offset = source.list_children_page("28", offset=50, limit=25)

        self.assertEqual(len(items), 1)
        self.assertEqual(total, 1)
        self.assertIsNone(next_offset)
        self.assertEqual(bridge.requests, [("list_children", {"parent_id": 28, "offset": 50, "limit": 25})])

    def test_capabilities_are_explicit(self) -> None:
        source = AndroidMacMtpSource(FakeBridge(), SourceIdentity("id", "Google", "Pixel", "Pixel", "test"))
        self.assertIn("list_children", source.capabilities())
        self.assertIn("paged_children", source.capabilities())
        self.assertIn("find_child", source.capabilities())
        self.assertIn("stream_object", source.capabilities())

    def test_bridge_allows_helper_to_exit_cleanly_before_terminating(self) -> None:
        class Input:
            closed = False

            def close(self) -> None:
                self.closed = True

        class Process:
            def __init__(self) -> None:
                self.stdin = Input()
                self.stdout = None
                self.stderr = None
                self.terminated = False
                self.waited = False

            def poll(self):
                return None

            def wait(self, timeout):
                self.waited = True
                return 0

            def terminate(self):
                self.terminated = True

        process = Process()
        bridge = JsonLineBridge(["helper"], runner=lambda *args, **kwargs: process)
        bridge.close()
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.waited)
        self.assertFalse(process.terminated)


if __name__ == "__main__":
    unittest.main()
