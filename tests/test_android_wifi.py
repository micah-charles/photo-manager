from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from photovault.sources.android_wifi import AndroidCompanionWifiSource


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


class AndroidWifiTests(unittest.TestCase):
    def test_identity_manifest_and_range_stream(self) -> None:
        seen = []
        def fake_open(request, timeout):
            seen.append((request.full_url, request.headers.get("Range")))
            if "/api/device" in request.full_url:
                return Response(json.dumps({"ok": True, "device": {"device_id": "installed-uuid", "manufacturer": "Google", "model": "Pixel", "media_count": 1}}).encode())
            if "/api/media?" in request.full_url:
                return Response(json.dumps({"ok": True, "items": [{"object_id": "7", "name": "x.jpg", "mime_type": "image/jpeg", "size_bytes": 3, "date_taken": 0, "modified_at": 0, "latitude": 55.9533, "longitude": -3.1883}]}).encode())
            return Response(b"abc")
        with patch("photovault.sources.android_wifi.urlopen", fake_open):
            source = AndroidCompanionWifiSource("http://phone:8765", "secret")
            self.assertEqual(source.identity().adapter, "android_companion_wifi")
            item = list(source.list_children(None))[0]
            self.assertEqual((item.name, item.source_latitude, item.source_longitude), ("x.jpg", 55.9533, -3.1883))
            sink = io.BytesIO(); metrics = source.stream_object("7", sink, offset=2)
        self.assertEqual(sink.getvalue(), b"abc")
        self.assertEqual(metrics["bytes_received"], 3)
        self.assertTrue(seen[-1][0].endswith("/api/media/7?token=secret"))
        self.assertEqual(seen[-1][1], "bytes=2-")

    def test_persistent_companion_id_is_independent_of_ip_address(self) -> None:
        def fake_open(request, timeout):
            return Response(json.dumps({"ok": True, "device": {"device_id": "installed-uuid", "manufacturer": "Google", "model": "Pixel"}}).encode())
        with patch("photovault.sources.android_wifi.urlopen", fake_open):
            first = AndroidCompanionWifiSource("http://192.168.1.10:8765", "secret").identity()
            second = AndroidCompanionWifiSource("http://192.168.1.11:8765", "secret").identity()
        self.assertEqual(first.source_id, second.source_id)

    def test_folder_inventory_count_and_paging(self) -> None:
        seen = []
        def fake_open(request, timeout):
            seen.append(request.full_url)
            if "/api/device?" in request.full_url:
                return Response(json.dumps({"ok": True, "device": {"manufacturer": "Google", "model": "Pixel"}}).encode())
            if "/api/folders?" in request.full_url:
                return Response(json.dumps({"ok": True, "folders": [{"relative_path": "DCIM/Camera/", "count": 2, "images": 1, "videos": 1, "size_bytes": 9}]}).encode())
            if "/api/media/count?" in request.full_url:
                return Response(json.dumps({"ok": True, "count": 2}).encode())
            if "/api/media?" in request.full_url:
                return Response(json.dumps({"ok": True, "items": [{"object_id": "8", "name": "camera.jpg", "mime_type": "image/jpeg", "size_bytes": 9, "date_taken": 0, "modified_at": 0}]}).encode())
            raise AssertionError(request.full_url)
        with patch("photovault.sources.android_wifi.urlopen", fake_open):
            source = AndroidCompanionWifiSource("http://phone:8765", "secret")
            folders = source.folders()
            self.assertEqual(folders[0].relative_path, "DCIM/Camera/")
            self.assertEqual((folders[0].count, folders[0].size_bytes), (2, 9))
            self.assertEqual(source.folder_count("DCIM/Camera"), 2)
            self.assertEqual(source.list_folder_page("DCIM/Camera", offset=500, limit=500, oldest_first=True)[0].name, "camera.jpg")
        self.assertTrue(any("relative_path=DCIM%2FCamera" in url for url in seen))
        self.assertTrue(any("offset=500" in url for url in seen))
        self.assertTrue(any("sort=oldest" in url for url in seen))
