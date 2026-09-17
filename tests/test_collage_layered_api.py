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

from PIL import Image, ImageDraw

from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity
from photovault.web.server import PhotoVaultHandler, ThreadingHTTPServer


class _Provider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "layered-api-volume", "Layered API volume")


def _png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class LayeredTemplateApiTests(unittest.TestCase):
    def test_upload_import_and_document_keep_template_layers_and_mask_url(self):
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

            foreground = Image.new("RGBA", (200, 200), (255, 255, 255, 0))
            mask = Image.new("L", (200, 200), 0)
            ImageDraw.Draw(mask).rectangle((20, 20, 180, 180), fill=255)
            manifest = {
                "format": "PhotoManager AI Design Package", "schema_version": 2,
                "package_id": "request", "catalog_id": catalog.stem, "design": "design.json",
                "photo_assets": [{"label": "A01", "asset_id": asset_id}], "assets": [],
                "capabilities": ["layered-template", "transparent-photo-slots"],
                "template": {
                    "foreground": "template/foreground.png",
                    "masks": {"A01": "template/masks/A01.png"},
                    "slots": {"A01": {"role": "hero", "x_mm": 10, "y_mm": 10, "width_mm": 80, "height_mm": 80}},
                },
            }
            design = {
                "format": "CollageDesignSpec", "schema_version": 2, "catalog_id": catalog.stem,
                "page_spec": {"type": "single", "width_mm": 100, "height_mm": 100},
                "assets": [{"label": "A01", "asset_id": asset_id}],
                "alternatives": [{"id": "layered-alt", "elements": [{
                    "id": "photo-01", "type": "photo", "asset_id": "A01", "slot_id": "A01",
                    "x_mm": 10, "y_mm": 10, "width_mm": 80, "height_mm": 80, "z_index": 1,
                }]}],
            }
            archive_bytes = io.BytesIO()
            with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("design.json", json.dumps(design))
                archive.writestr("template/foreground.png", _png(foreground))
                archive.writestr("template/masks/A01.png", _png(mask))

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
                connection.request(method, path, encoded, {"Content-Type": "application/json"} if encoded else {})
                response = connection.getresponse()
                raw = response.read()
                content_type = response.getheader("Content-Type", "")
                status = response.status
                connection.close()
                return status, json.loads(raw) if "application/json" in content_type else raw

            status, uploaded = request("POST", "/api/collage/design-import-packages", {"package_zip_base64": base64.b64encode(archive_bytes.getvalue()).decode()})
            self.assertEqual(status, 201)
            self.assertEqual(len(uploaded["template_assets"]), 2)
            self.assertEqual(uploaded["spec"]["layered_template"]["slots"]["A01"]["role"], "hero")

            status, imported = request("POST", "/api/collage/design-imports", {"package_id": uploaded["package_id"], "spec": uploaded["spec"]})
            self.assertEqual(status, 201)
            document = imported["document"]
            self.assertEqual(document["elements"][0]["type"], "photo")
            self.assertEqual(document["elements"][0]["template_slot_id"], "A01")
            self.assertEqual(document["elements"][-1]["template_layer"], "foreground")
            self.assertTrue(document["elements"][-1]["locked"])
            self.assertTrue(document["elements"][0]["template_mask_url"].startswith("/api/collage/design-assets/pa_"))

            mask_id = uploaded["spec"]["layered_template"]["mask_asset_ids"]["A01"]
            status, mask_bytes = request("GET", f"/api/collage/design-assets/{mask_id}")
            self.assertEqual(status, 200)
            with Image.open(io.BytesIO(mask_bytes)) as normalised:
                self.assertEqual(normalised.mode, "RGBA")
                self.assertEqual(normalised.getpixel((0, 0))[3], 0)
                self.assertEqual(normalised.getpixel((100, 100))[3], 255)

            status, exported = request("POST", "/api/collage/design-packages", {
                "asset_ids": [asset_id], "page_spec": document["page_spec"], "current_document": document,
                "mode": "improve_existing",
            })
            self.assertEqual(status, 201)
            status, package_bytes = request("GET", exported["download"])
            self.assertEqual(status, 200)
            with zipfile.ZipFile(io.BytesIO(package_bytes)) as package:
                names = set(package.namelist())
                self.assertIn("template/foreground.png", names)
                self.assertIn("template/masks/A01.png", names)
                exported_manifest = json.loads(package.read("manifest.json"))
                self.assertEqual(exported_manifest["capabilities"], ["layered-template", "transparent-photo-slots"])


if __name__ == "__main__":
    unittest.main()
