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
                return Response(json.dumps({"ok": True, "device": {"manufacturer": "Google", "model": "Pixel", "media_count": 1}}).encode())
            if "/api/media?" in request.full_url:
                return Response(json.dumps({"ok": True, "items": [{"object_id": "7", "name": "x.jpg", "mime_type": "image/jpeg", "size_bytes": 3, "date_taken": 0, "modified_at": 0}]}).encode())
            return Response(b"abc")
        with patch("photovault.sources.android_wifi.urlopen", fake_open):
            source = AndroidCompanionWifiSource("http://phone:8765", "secret")
            self.assertEqual(source.identity().adapter, "android_companion_wifi")
            self.assertEqual(list(source.list_children(None))[0].name, "x.jpg")
            sink = io.BytesIO(); metrics = source.stream_object("7", sink, offset=2)
        self.assertEqual(sink.getvalue(), b"abc")
        self.assertEqual(metrics["bytes_received"], 3)
        self.assertTrue(seen[-1][0].endswith("/api/media/7?token=secret"))
        self.assertEqual(seen[-1][1], "bytes=2-")
