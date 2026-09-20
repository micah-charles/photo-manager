from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from photovault.catalog.scanner import register_volume, scan_volume
from photovault.catalog.organization import create_event, create_topic_section
from photovault.collage.projects import build_a4_design_spec
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity
from photovault.web.server import PhotoVaultHandler, ThreadingHTTPServer


class _Provider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "design-api-volume", "Design API volume")


class CollageDesignApiTests(unittest.TestCase):
    def test_a4_story_keeps_every_asset_and_adapts_dense_sections(self) -> None:
        section = {"title": "Conwy Castle", "topic_name": "Test trip"}
        asset_ids = [f"asset-{index:02d}" for index in range(1, 13)]
        spec, _, _ = build_a4_design_spec(section, asset_ids, {})
        elements = spec["alternatives"][0]["elements"]
        rendered = [element["asset_id"] for element in elements if element.get("type") == "photo"]
        self.assertEqual(rendered, asset_ids)
        self.assertEqual(spec["composition"]["rendered_asset_count"], len(asset_ids))
        self.assertTrue(spec["composition"]["all_assets_rendered"])
        self.assertGreaterEqual(spec["composition"]["editorial_slot_count"], 9)
        self.assertLessEqual(spec["composition"]["gallery_asset_count"], 3)

    def test_six_assets_use_a_complete_editorial_grid(self) -> None:
        section = {"title": "Bangor Cathedral", "topic_name": "Test trip"}
        asset_ids = [f"asset-{index:02d}" for index in range(1, 7)]
        spec, _, _ = build_a4_design_spec(section, asset_ids, {})
        photos = [element for element in spec["alternatives"][0]["elements"] if element.get("type") == "photo"]
        last = photos[-1]
        self.assertEqual(len(photos), len(asset_ids))
        self.assertEqual(spec["composition"]["gallery_asset_count"], 0)
        self.assertEqual(last["y_mm"], 128)
        self.assertGreater(last["height_mm"], 45)

    def test_ten_assets_use_a_complete_editorial_grid(self) -> None:
        section = {"title": "Castle views", "topic_name": "Test trip"}
        asset_ids = [f"asset-{index:02d}" for index in range(1, 11)]
        guidance = {"Castle views": {"hero_indices": [1], "subhero_indices": [2, 3], "supporting_indices": [4]}}
        spec, _, _ = build_a4_design_spec(section, asset_ids, guidance)
        photos = [element for element in spec["alternatives"][0]["elements"] if element.get("type") == "photo"]
        self.assertEqual(len(photos), len(asset_ids))
        self.assertEqual(spec["composition"]["gallery_asset_count"], 0)
        self.assertEqual(max(photo["y_mm"] for photo in photos), 166)
        self.assertEqual(sum(photo["y_mm"] == 166 for photo in photos), 5)

    def test_nine_assets_use_a_complete_editorial_grid(self) -> None:
        section = {"title": "Cable car", "topic_name": "Test trip"}
        asset_ids = [f"asset-{index:02d}" for index in range(1, 10)]
        guidance = {"Cable car": {"hero_indices": [1], "subhero_indices": [2, 3], "supporting_indices": [4]}}
        spec, _, _ = build_a4_design_spec(section, asset_ids, guidance)
        photos = [element for element in spec["alternatives"][0]["elements"] if element.get("type") == "photo"]
        self.assertEqual(len(photos), len(asset_ids))
        self.assertEqual(spec["composition"]["gallery_asset_count"], 0)
        self.assertEqual(sum(photo["y_mm"] == 166 for photo in photos), 4)

    def test_eight_assets_keep_two_subheroes_in_a_balanced_closing_grid(self) -> None:
        section = {"title": "Snowdown Mountatin 01", "topic_name": "Test trip"}
        asset_ids = [f"asset-{index:02d}" for index in range(1, 9)]
        guidance = {
            "Snowdown Mountatin 01": {
                "hero_indices": [1, 2],
                "subhero_indices": [2, 3],
            }
        }
        spec, _, subhero_ids = build_a4_design_spec(section, asset_ids, guidance)
        photos = [element for element in spec["alternatives"][0]["elements"] if element.get("type") == "photo"]
        self.assertEqual([photo["asset_id"] for photo in photos], asset_ids)
        self.assertEqual(spec["composition"]["gallery_asset_count"], 0)
        self.assertEqual(len(subhero_ids), 2)
        self.assertEqual(spec["composition"]["rendered_role_counts"]["secondary"], 2)
        self.assertEqual(sum(photo["y_mm"] == 169 for photo in photos), 3)

    def test_eight_photo_scenic_story_balances_people_anchor_and_fills_a4_field(self) -> None:
        section = {"title": "Snowdown Mountatin 01", "topic_name": "Test trip"}
        asset_ids = [f"asset-{index:02d}" for index in range(1, 9)]
        guidance = {
            "Snowdown Mountatin 01": {
                "layout_archetype": "scenic_hero",
                "composition_variant": "panorama_then_portraits",
                "hero_indices": [8, 5],
                "subhero_indices": [5, 6],
                "supporting_indices": [7],
                "detail_indices": [1, 2, 3, 4],
                "focus_x_by_index": {"5": 0.46, "6": 0.46, "7": 0.48},
                "focus_y_by_index": {"3": 0.40, "5": 0.43, "6": 0.46, "7": 0.46},
            }
        }
        spec, _, subhero_ids = build_a4_design_spec(section, asset_ids, guidance)
        photos = [element for element in spec["alternatives"][0]["elements"] if element.get("type") == "photo"]
        self.assertEqual(set(photo["asset_id"] for photo in photos), set(asset_ids))
        self.assertEqual(len({photo["asset_id"] for photo in photos}), len(asset_ids))
        self.assertEqual(spec["composition"]["gallery_asset_count"], 0)
        self.assertEqual(len(subhero_ids), 2)
        self.assertEqual([(photo["x_mm"], photo["y_mm"], photo["width_mm"], photo["height_mm"]) for photo in photos[:2]], [(14, 45, 92, 72), (110, 45, 86, 72)])
        self.assertEqual(sum(photo["y_mm"] == 185 for photo in photos), 3)
        self.assertEqual(next(photo for photo in photos if photo["asset_id"] == "asset-05")["image"]["focus_x"], 0.46)
        self.assertEqual(next(photo for photo in photos if photo["asset_id"] == "asset-03")["image"]["focus_y"], 0.40)

    def test_nine_photo_ridge_story_promotes_people_subhero_and_fills_a4_field(self) -> None:
        section = {"title": "Snowdown Mountatin 02", "topic_name": "Test trip"}
        asset_ids = [f"asset-{index:02d}" for index in range(1, 10)]
        guidance = {
            "Snowdown Mountatin 02": {
                "layout_archetype": "scenic_hero",
                "composition_variant": "ridge_people_right",
                "hero_indices": [7, 2],
                "subhero_indices": [9, 3],
                "supporting_indices": [1],
                "detail_indices": [2, 4, 5, 6, 8],
                "focus_y_by_index": {"7": 0.48, "9": 0.54},
            }
        }
        spec, hero_ids, subhero_ids = build_a4_design_spec(section, asset_ids, guidance)
        photos = [element for element in spec["alternatives"][0]["elements"] if element.get("type") == "photo"]
        self.assertEqual(set(photo["asset_id"] for photo in photos), set(asset_ids))
        self.assertEqual(len(set(photo["asset_id"] for photo in photos)), len(asset_ids))
        self.assertEqual(spec["composition"]["gallery_asset_count"], 0)
        self.assertEqual(hero_ids, ["asset-07"])
        self.assertEqual(subhero_ids, ["asset-09", "asset-03"])
        self.assertEqual([(photo["x_mm"], photo["y_mm"], photo["width_mm"], photo["height_mm"]) for photo in photos[:2]], [(14, 45, 58, 78), (78, 45, 118, 78)])
        self.assertEqual(sum(photo["y_mm"] == 189 for photo in photos), 4)
        self.assertEqual(next(photo for photo in photos if photo["asset_id"] == "asset-09")["image"]["focus_y"], 0.54)

    def test_role_summary_matches_roles_that_were_rendered(self) -> None:
        section = {"title": "Castle views", "topic_name": "Test trip"}
        asset_ids = [f"asset-{index:02d}" for index in range(1, 13)]
        guidance = {"Castle views": {"hero_indices": [1, 2], "subhero_indices": [2, 3, 4, 5]}}
        spec, hero_ids, subhero_ids = build_a4_design_spec(section, asset_ids, guidance)
        photos = [element for element in spec["alternatives"][0]["elements"] if element.get("type") == "photo"]
        rendered_secondary = [photo["asset_id"] for photo in photos if photo.get("role") == "secondary"]
        self.assertEqual(hero_ids, [photo["asset_id"] for photo in photos if photo.get("role") == "hero"][:1])
        self.assertEqual(subhero_ids, rendered_secondary)
        self.assertEqual(spec["composition"]["subheroes"], rendered_secondary)
        self.assertEqual(spec["composition"]["rendered_role_counts"]["secondary"], len(rendered_secondary))
        self.assertEqual(len(photos), len(asset_ids))

    def test_export_validate_import_and_save_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "photos"
            root.mkdir()
            Image.new("RGB", (320, 240), "#d36c5c").save(root / "one.jpg")
            oriented = Image.new("RGB", (240, 320), "#4b8f8c")
            exif = Image.Exif()
            exif[274] = 6  # camera-native portrait pixels, displayed landscape
            oriented.save(root / "two.jpg", exif=exif)
            catalog = Path(directory) / "catalog.db"
            db = connect(catalog)
            volume_id = register_volume(db, root, _Provider())
            scan_volume(db, volume_id, root)
            asset_ids = [str(row[0]) for row in db.execute("SELECT id FROM assets ORDER BY id")]
            db.close()

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

            status, exported = request(
                "POST",
                "/api/collage/design-packages",
                {
                    "asset_ids": asset_ids,
                    "page_spec": {"type": "single", "width_mm": 300, "height_mm": 300},
                    "topic_id": "topic-test",
                    "section_id": "section-test",
                },
            )
            self.assertEqual(status, 201)
            self.assertIsInstance(exported, dict)
            package_id = str(exported["package_id"])
            manifest = exported["manifest"]
            self.assertNotIn("absolute_path", json.dumps(manifest))
            self.assertNotIn("thumbnail_path", json.dumps(manifest))
            oriented_asset = next(item for item in manifest["photo_assets"] if item["orientation"] == 6)
            self.assertEqual(oriented_asset["width"], 240)
            self.assertEqual(oriented_asset["height"], 320)

            status, package_bytes = request("GET", exported["download"])
            self.assertEqual(status, 200)
            self.assertIsInstance(package_bytes, bytes)
            with zipfile.ZipFile(__import__("io").BytesIO(package_bytes)) as archive:
                names = set(archive.namelist())
                self.assertIn("design-package.json", names)
                self.assertIn("contact-sheet.jpg", names)
                self.assertIn("thumbnails/A01.jpg", names)
                self.assertIn("README-for-AI.txt", names)
                package = json.loads(archive.read("design-package.json"))
                oriented_index = next(index for index, item in enumerate(package["assets"]) if item["orientation"] == 6)
                with Image.open(archive.open(f"thumbnails/A{oriented_index + 1:02d}.jpg")) as normalized:
                    self.assertGreater(normalized.width, normalized.height)

            spec = {
                "format": "CollageDesignSpec",
                "schema_version": 1,
                "package_id": package_id,
                "alternatives": [{
                    "id": "alt-1",
                    "style": "test",
                    "elements": [
                        {"id": "background", "type": "rectangle", "x_mm": 0, "y_mm": 0,
                         "width_mm": 300, "height_mm": 300, "fill": "#f5f2ed", "z_index": 0},
                        {"id": "photo-1", "type": "photo", "asset_id": "A01", "x_mm": 10, "y_mm": 10,
                         "width_mm": 120, "height_mm": 120, "image": {"zoom": 1.2}, "z_index": 1},
                        {"id": "title", "type": "text", "content": "Test page", "x_mm": 20, "y_mm": 260,
                         "width_mm": 100, "height_mm": 15, "z_index": 2},
                    ],
                }],
            }
            status, validated = request("POST", "/api/collage/design-imports/validate", {"spec": spec})
            self.assertEqual(status, 200)
            self.assertTrue(validated["valid"])
            self.assertEqual(validated["alternatives"][0]["photos"], 1)

            status, imported = request("POST", "/api/collage/design-imports", {"spec": spec, "alternative_index": 0})
            self.assertEqual(status, 201)
            document = imported["document"]
            self.assertEqual(document["schema_version"], 2)
            self.assertEqual(document["elements"][1]["photo_id"], asset_ids[0])
            document_url = imported["document_url"]

            status, read_back = request("GET", document_url)
            self.assertEqual(status, 200)
            self.assertEqual(read_back["document_id"], document["document_id"])

            document["elements"][1]["rotation_deg"] = 9
            status, saved = request("POST", "/api/collage/documents", document)
            self.assertEqual(status, 201)
            self.assertTrue(saved["variant"])
            self.assertNotEqual(saved["document"]["document_id"], document["document_id"])
            self.assertEqual(saved["document"]["elements"][1]["rotation_deg"], 9)

    def test_project_generates_and_lists_a4_section_collages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "photos"
            root.mkdir()
            Image.new("RGB", (320, 240), "#d36c5c").save(root / "one.jpg")
            Image.new("RGB", (240, 320), "#4b8f8c").save(root / "two.jpg")
            Image.new("RGB", (320, 240), "#8f7ac4").save(root / "three.jpg")
            catalog = Path(directory) / "catalog.db"
            db = connect(catalog)
            volume_id = register_volume(db, root, _Provider())
            scan_volume(db, volume_id, root)
            asset_ids = [str(row[0]) for row in db.execute("SELECT id FROM assets ORDER BY id")]
            topic_id = create_event(db, "2026 Apr Mothers Visit - 0412")
            section_id = create_topic_section(db, topic_id, "Bangor Cathedral", asset_ids)
            db.close()

            server = ThreadingHTTPServer(("127.0.0.1", 0), PhotoVaultHandler)
            server.catalog_path = catalog
            server.collage_runs = {}
            server.collage_jobs = {}
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)

            def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                encoded = json.dumps(body).encode() if body is not None else None
                headers = {"Content-Type": "application/json"} if encoded is not None else {}
                connection.request(method, path, encoded, headers)
                response = connection.getresponse()
                payload = json.loads(response.read())
                status = response.status
                connection.close()
                return status, payload

            status, project = request("POST", "/api/collage/projects", {"name": "0412 A4 test"})
            self.assertEqual(status, 201)
            project_id = project["project_id"]
            status, generated = request("POST", f"/api/collage/projects/{project_id}/generate", {"topic_ids": [topic_id]})
            self.assertEqual(status, 201)
            self.assertEqual(generated["generated"], 1)
            self.assertEqual(generated["project"]["documents"][0]["section_id"], section_id)
            document_id = generated["project"]["documents"][0]["document_id"]
            status, document = request("GET", f"/api/collage/documents/{document_id}")
            self.assertEqual(status, 200)
            self.assertEqual(document["page_spec"]["preset_id"], "a4-portrait")
            self.assertEqual(document["metadata"]["project_id"], project_id)
            self.assertEqual(len(document["frames"]), 3)
            self.assertEqual({frame["photo_id"] for frame in document["frames"]}, set(asset_ids))
            self.assertEqual(sum(frame.get("role") == "hero" for frame in document["frames"]), 1)
            self.assertEqual(document["metadata"]["composition"]["rendered_asset_count"], 3)


if __name__ == "__main__":
    unittest.main()
