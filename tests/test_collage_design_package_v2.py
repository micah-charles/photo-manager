from __future__ import annotations

import base64
import http.client
import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from photovault.catalog.scanner import register_volume, scan_volume
from photovault.collage.design_assets import sanitize_svg
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity
from photovault.web.server import PhotoVaultHandler, ThreadingHTTPServer


class _Provider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "design-package-v2-volume", "Design package v2 volume")


class CollageDesignPackageV2Tests(unittest.TestCase):
    def test_safe_svg_allows_namespace_and_rejects_script(self) -> None:
        safe = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="#e6eee2"/></svg>'
        cleaned = sanitize_svg(safe)
        self.assertIn(b"circle", cleaned)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            sanitize_svg(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')

    def test_uploads_sanitizes_decorative_asset_and_round_trips_editable_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "photos"
            root.mkdir()
            Image.new("RGB", (320, 240), "#d36c5c").save(root / "one.jpg")
            catalog = Path(directory) / "catalog.db"
            db = connect(catalog)
            volume_id = register_volume(db, root, _Provider())
            scan_volume(db, volume_id, root)
            asset_id = str(db.execute("SELECT id FROM assets ORDER BY id LIMIT 1").fetchone()[0])
            db.close()

            svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="#e6eee2"/></svg>'
            package_manifest = {
                "format": "PhotoManager AI Design Package", "schema_version": 2,
                "package_id": "request", "catalog_id": catalog.stem, "design": "design.json",
                "photo_assets": [{"label": "A01", "asset_id": asset_id}],
                "assets": [{"id": "D01", "path": "assets/flower.svg", "media_type": "image/svg+xml"}],
            }
            design = {
                "format": "CollageDesignSpec", "schema_version": 2, "catalog_id": catalog.stem,
                "page_spec": {"type": "single", "width_mm": 300, "height_mm": 300},
                "assets": [{"label": "A01", "asset_id": asset_id}],
                "alternatives": [{"id": "decorative-alt", "name": "Decorative test", "elements": [
                    {"id": "photo-01", "type": "photo", "asset_id": "A01", "role": "hero", "x_mm": 20, "y_mm": 20, "width_mm": 120, "height_mm": 120},
                    {"id": "flower-01", "type": "design_asset", "asset_ref": "assets/flower.svg", "x_mm": 160, "y_mm": 20, "width_mm": 50, "height_mm": 50, "z_index": 5},
                    {"id": "title", "type": "text", "content": "Garden", "x_mm": 20, "y_mm": 260, "width_mm": 100, "height_mm": 15, "text_style": {"font_id": "serif", "font_size_pt": 12}, "z_index": 6},
                ]}],
            }
            archive_bytes = io.BytesIO()
            with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(package_manifest))
                archive.writestr("design.json", json.dumps(design))
                archive.writestr("assets/flower.svg", svg)

            server = ThreadingHTTPServer(("127.0.0.1", 0), PhotoVaultHandler)
            server.catalog_path = catalog
            server.collage_runs = {}
            server.collage_jobs = {}
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)

            def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict | bytes]:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                encoded = json.dumps(body).encode() if body is not None else None
                headers = {"Content-Type": "application/json"} if encoded is not None else {}
                connection.request(method, path, encoded, headers)
                response = connection.getresponse()
                raw = response.read()
                status = response.status
                content_type = response.getheader("Content-Type", "")
                connection.close()
                return status, json.loads(raw) if "application/json" in content_type else raw

            upload = {"package_zip_base64": base64.b64encode(archive_bytes.getvalue()).decode("ascii")}
            status, uploaded = request("POST", "/api/collage/design-import-packages", upload)
            self.assertEqual(status, 201)
            self.assertTrue(uploaded["valid"])
            self.assertEqual(uploaded["alternatives"][0]["design_assets"], 1)
            managed = uploaded["decorative_assets"][0]["package_asset_id"]
            self.assertTrue(managed.startswith("pa_"))

            status, asset_bytes = request("GET", f"/api/collage/design-assets/{managed}")
            self.assertEqual(status, 200)
            self.assertIn(b"circle", asset_bytes)

            status, imported = request("POST", "/api/collage/design-imports", {"package_id": uploaded["package_id"], "spec": uploaded["spec"]})
            self.assertEqual(status, 201)
            document = imported["document"]
            design_element = next(item for item in document["elements"] if item["type"] == "design_asset")
            self.assertEqual(design_element["asset_id"], managed)
            self.assertEqual(document["metadata"]["source"], "CollageDesignSpec v2")

            status, saved = request("POST", "/api/collage/documents", document)
            self.assertEqual(status, 201)
            self.assertTrue(saved["variant"])
            self.assertEqual(saved["document"]["elements"][1]["asset_id"], managed)


if __name__ == "__main__":
    unittest.main()
