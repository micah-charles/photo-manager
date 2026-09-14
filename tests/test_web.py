from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.library import LibraryQuery
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.catalog.organization import add_assets_to_event, create_event
from photovault.catalog.thumbnail_jobs import build_missing_thumbnails, thumbnail_status
from photovault.platform.base import VolumeIdentity
from photovault.web.server import STATIC_ROOT, _decode_cursor, library_payload, navigation_payload, topics_payload


class WebLibraryTests(unittest.TestCase):
    def test_library_payload_groups_real_catalog_rows_for_month(self) -> None:
        class Provider:
            def identify(self, path: Path) -> VolumeIdentity:
                return VolumeIdentity("web", "web-volume", "Web test volume")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"
            root.mkdir()
            (root / "july.jpg").write_bytes(b"july")
            db = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(db, root, Provider())
            scan_volume(db, volume_id, root)
            db.execute("UPDATE asset_locations SET modified_ns=?", (1784073600 * 1_000_000_000,))
            db.commit()
            payload = library_payload(db, LibraryQuery(captured_month="2026-07", limit=20))
            self.assertEqual(payload["total"], 1)
            self.assertEqual(payload["items"][0]["filename"], "july.jpg")
            self.assertIn("2026-07-15", payload["days"])
            db.close()

    def test_web_static_shell_is_present(self) -> None:
        self.assertTrue((STATIC_ROOT / "index.html").is_file())
        self.assertTrue((STATIC_ROOT / "style.css").is_file())
        self.assertTrue((STATIC_ROOT / "app.js").is_file())

    def test_creator_mode_has_first_class_creation_methods(self) -> None:
        collage = (STATIC_ROOT / "collage_v2.html").read_text(encoding="utf-8")
        for marker in (
            'id="method-ai"',
            'id="method-native"',
            'id="method-cewe"',
            'id="method-bsp"',
            'id="export-design"',
            'id="import-ai-design"',
            'id="creator-alternative"',
            'id="start-blank"',
            'collage_creator_mode.js',
        ):
            self.assertIn(marker, collage)
        self.assertIn("Nothing is sent to an AI service automatically", collage)

        editor = (STATIC_ROOT / "fabric_spike_v2.html").read_text(encoding="utf-8")
        self.assertIn('id="ai-document-summary"', editor)
        self.assertIn('id="run-control"', editor)

    def test_topics_payload_exposes_editable_event_and_count(self) -> None:
        class Provider:
            def identify(self, path: Path) -> VolumeIdentity:
                return VolumeIdentity("web", "web-volume", "Web test volume")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"
            root.mkdir()
            (root / "photo.jpg").write_bytes(b"photo")
            db = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(db, root, Provider())
            scan_volume(db, volume_id, root)
            asset_id = str(db.execute("SELECT id FROM assets").fetchone()[0])
            event_id = create_event(db, "Scotland Trip 2026", start_datetime="2026-08-22", end_datetime="2026-08-26")
            add_assets_to_event(db, event_id, [asset_id])
            payload = topics_payload(db)
            self.assertEqual(payload["topics"][0]["name"], "Scotland Trip 2026")
            self.assertEqual(payload["topics"][0]["item_count"], 1)
            self.assertEqual(payload["topics"][0]["start_datetime"], "2026-08-22")
            db.close()

    def test_thumbnail_job_is_batched_and_records_ready_status(self) -> None:
        class Provider:
            def identify(self, path: Path) -> VolumeIdentity:
                return VolumeIdentity("web", "web-volume", "Web test volume")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"
            root.mkdir()
            (root / "photo.jpg").write_bytes(b"not a real jpeg")
            db = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(db, root, Provider())
            scan_volume(db, volume_id, root)
            result = build_missing_thumbnails(db, cache_root=Path(directory) / "thumbs")
            status = thumbnail_status(db)
            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(status["pending"], 0)
            self.assertEqual(status["failed"], 1)
            db.close()

    def test_library_cursor_advances_without_repeating_asset(self) -> None:
        class Provider:
            def identify(self, path: Path) -> VolumeIdentity:
                return VolumeIdentity("web", "web-volume", "Web test volume")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"
            root.mkdir()
            (root / "a.jpg").write_bytes(b"a")
            (root / "b.jpg").write_bytes(b"b")
            db = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(db, root, Provider())
            scan_volume(db, volume_id, root)
            first = library_payload(db, LibraryQuery(limit=1, sort="captured_desc_id"))
            captured, asset_id = _decode_cursor(first["next_cursor"])
            second = library_payload(db, LibraryQuery(limit=1, sort="captured_desc_id", after_captured=captured, after_asset_id=asset_id))
            self.assertEqual(len(second["items"]), 1)
            self.assertNotEqual(first["items"][0]["asset_id"], second["items"][0]["asset_id"])
            db.close()

    def test_navigation_payload_contains_browse_facets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "catalog.db")
            payload = navigation_payload(db)
            self.assertEqual(set(payload), {"people", "places", "tags", "categories", "sources", "collections"})
            for value in payload.values():
                self.assertIsInstance(value, list)
            db.close()

    def test_library_payload_supports_year_range_for_year_navigation(self) -> None:
        class Provider:
            def identify(self, path: Path) -> VolumeIdentity:
                return VolumeIdentity("web", "web-volume", "Web test volume")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"
            root.mkdir()
            (root / "photo.jpg").write_bytes(b"photo")
            db = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(db, root, Provider())
            scan_volume(db, volume_id, root)
            db.execute("UPDATE asset_locations SET modified_ns=?", (1784073600 * 1_000_000_000,))
            db.commit()
            payload = library_payload(db, LibraryQuery(captured_from="2026-01-01", captured_to="2026-12-31", limit=20))
            self.assertEqual(payload["total"], 1)
            db.close()
