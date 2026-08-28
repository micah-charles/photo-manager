from __future__ import annotations

import unittest
from datetime import datetime

from photovault.sources.android import AndroidMacMtpSource
from photovault.sources.base import SourceIdentity


class FakeBridge:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []

    def request(self, operation: str, **arguments):
        self.requests.append((operation, arguments))
        if operation == "list_storages":
            return {"ok": True, "storages": [{"storage_id": 65537, "name": "Internal storage", "capacity_bytes": 10, "free_bytes": 5}]}
        if operation == "list_children":
            return {"ok": True, "items": [{"object_id": 28, "parent_id": 10, "name": "Camera", "format": 0x3001}]}
        if operation == "object_info":
            return {"ok": True, "item": {"object_id": 675, "parent_id": 28, "name": "photo.jpg", "format": 0x3801, "size_bytes": 123, "created_at": "20260828T120000", "modified_at": "20260828T120100"}}
        raise AssertionError(operation)


class AndroidSourceTests(unittest.TestCase):
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
        self.assertEqual(bridge.requests[1], ("list_children", {"parent_id": 10}))

    def test_capabilities_are_explicit(self) -> None:
        source = AndroidMacMtpSource(FakeBridge(), SourceIdentity("id", "Google", "Pixel", "Pixel", "test"))
        self.assertIn("list_children", source.capabilities())
        self.assertNotIn("open_read_stream", source.capabilities())


if __name__ == "__main__":
    unittest.main()
