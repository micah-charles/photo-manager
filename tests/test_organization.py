from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.organization import (
    add_assets_to_event,
    assign_place,
    assign_tags,
    create_event,
    create_place,
    create_tag,
    list_events,
    list_places,
    list_sources,
    list_tags,
    remove_assets_from_event,
    remove_place,
    remove_tags,
    set_asset_source,
    set_review,
    suggest_events_from_dates,
)
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("org-volume", "organisation-volume", "Organisation volume")


class OrganisationTests(unittest.TestCase):
    def _catalog(self, temp: str):
        root = Path(temp) / "photos"
        root.mkdir()
        (root / "one.jpg").write_bytes(b"one")
        (root / "two.jpg").write_bytes(b"two")
        db = connect(Path(temp) / "catalog.db")
        volume_id = register_volume(db, root, FixedProvider())
        scan_volume(db, volume_id, root)
        source = db.execute("SELECT source_id, source_type FROM source_profiles WHERE source_id=?", (f"folder:{volume_id}",)).fetchone()
        self.assertEqual(tuple(source), (f"folder:{volume_id}", "local_folder"))
        location_source = db.execute("SELECT source_id FROM asset_locations LIMIT 1").fetchone()[0]
        self.assertEqual(location_source, f"folder:{volume_id}")
        return db

    def test_source_provenance_is_separate_from_volume_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = self._catalog(temp)
            db.execute(
                """INSERT INTO source_profiles
                   (id, source_id, manufacturer, model, display_name, adapter, first_seen, last_seen, source_type)
                   VALUES ('nikon', 'nikon-z6', 'Nikon', 'Z6', 'Nikon Z6', 'folder', datetime('now'), datetime('now'), 'camera')"""
            )
            db.commit()
            asset_id = db.execute("SELECT id FROM assets ORDER BY id LIMIT 1").fetchone()[0]
            set_asset_source(db, asset_id, "nikon-z6")
            row = list_sources(db)[0]
            self.assertEqual((row[1], row[2], row[7]), ("Nikon Z6", "camera", 1))
            self.assertEqual(db.execute("SELECT source_id FROM asset_locations WHERE asset_id=?", (asset_id,)).fetchone()[0], "nikon-z6")
            db.close()

    def test_event_tags_place_and_review_are_catalog_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = self._catalog(temp)
            assets = [row[0] for row in db.execute("SELECT id FROM assets ORDER BY id")]
            event_id = create_event(db, "Scotland Trip 2026", start_datetime="2026-08-22", end_datetime="2026-08-26", event_type="trip")
            self.assertEqual(add_assets_to_event(db, event_id, assets), 2)
            self.assertEqual(list_events(db)[0].item_count, 2)
            self.assertEqual(remove_assets_from_event(db, event_id, [assets[0]]), 1)
            tag_id = create_tag(db, "Family")
            self.assertEqual(assign_tags(db, assets, [tag_id]), 2)
            self.assertEqual(list_tags(db)[0].item_count, 2)
            self.assertEqual(remove_tags(db, [assets[0]], [tag_id]), 1)
            place_id = create_place(db, "Edinburgh", city="Edinburgh")
            self.assertEqual(assign_place(db, [assets[0]], place_id), 1)
            self.assertEqual(list_places(db)[0].item_count, 1)
            self.assertEqual(remove_place(db, [assets[0]], place_id), 1)
            self.assertEqual(list_places(db)[0].item_count, 0)
            self.assertEqual(set_review(db, assets, status="PICKED", rating=4), 2)
            self.assertEqual(tuple(db.execute("SELECT review_status, rating FROM asset_reviews ORDER BY asset_id").fetchone()), ("PICKED", 4))
            self.assertTrue((Path(temp) / "photos" / "one.jpg").exists())
            db.close()

    def test_user_review_metadata_validates_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = self._catalog(temp)
            asset_id = db.execute("SELECT id FROM assets LIMIT 1").fetchone()[0]
            with self.assertRaises(ValueError):
                set_review(db, [asset_id], status="DELETE")
            with self.assertRaises(ValueError):
                set_review(db, [asset_id], rating=6)
            db.close()

    def test_date_event_suggestions_are_repeatable_and_marked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = self._catalog(temp)
            assets = [row[0] for row in db.execute("SELECT id FROM assets ORDER BY id")]
            for asset_id, captured in zip(assets, ("2026-08-23T10:00:00", "2026-08-23T11:00:00")):
                db.execute(
                    "UPDATE media_metadata SET capture_datetime=?, date_source=? WHERE asset_id=?",
                    (captured, "test", asset_id),
                )
            db.commit()
            self.assertEqual(suggest_events_from_dates(db), 2)
            self.assertEqual(suggest_events_from_dates(db), 0)
            row = db.execute("SELECT is_suggested, COUNT(*) FROM events e JOIN event_assets ea ON ea.event_id=e.id GROUP BY e.id").fetchone()
            self.assertEqual(tuple(row), (1, 2))
            db.close()
