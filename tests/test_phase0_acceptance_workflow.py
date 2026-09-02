from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.collections import add_to_user_collection, create_user_collection
from photovault.catalog.library import LibraryQuery, list_library_items
from photovault.catalog.organization import (
    add_assets_to_event,
    assign_place,
    assign_tags,
    create_event,
    create_place,
    create_tag,
    set_asset_source,
    set_review,
    set_source_time_offset,
)
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.catalog.people import assign_person, create_person
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class AcceptanceProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("acceptance", path.name, f"Acceptance {path.name}")


class Phase0AcceptanceWorkflowTests(unittest.TestCase):
    def test_multi_source_organisation_and_safe_review_journey(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            phone = root / "phone"
            camera = root / "camera"
            phone.mkdir()
            camera.mkdir()
            phone_photo = phone / "phone.jpg"
            camera_photo = camera / "camera.jpg"
            phone_photo.write_bytes(b"phone-original")
            camera_photo.write_bytes(b"camera-original")
            phone_bytes = phone_photo.read_bytes()
            camera_bytes = camera_photo.read_bytes()

            db = connect(root / "catalog.db")
            phone_volume = register_volume(db, phone, AcceptanceProvider())
            camera_volume = register_volume(db, camera, AcceptanceProvider())
            scan_volume(db, phone_volume, phone)
            scan_volume(db, camera_volume, camera)
            assets = {
                row["filename"]: row["asset_id"]
                for row in db.execute("SELECT filename, asset_id FROM asset_locations")
            }
            phone_asset, camera_asset = assets["phone.jpg"], assets["camera.jpg"]

            camera_source = "camera-source"
            db.execute(
                """INSERT INTO source_profiles
                   (id, source_id, manufacturer, model, display_name, adapter,
                    first_seen, last_seen, source_type)
                   VALUES (?, ?, 'Nikon', 'Z6', 'Nikon Z6', 'local_folder',
                           datetime('now'), datetime('now'), 'camera')""",
                (camera_source, camera_source),
            )
            db.commit()
            set_asset_source(db, camera_asset, camera_source)
            db.execute(
                "UPDATE media_metadata SET capture_datetime=? WHERE asset_id IN (?, ?)",
                ("2026-08-23T10:00:00", phone_asset, camera_asset),
            )
            db.commit()

            place_id = create_place(db, "Edinburgh", city="Edinburgh")
            event_id = create_event(
                db, "Scotland Trip 2026", start_datetime="2026-08-23",
                end_datetime="2026-08-23", event_type="trip", default_place_id=place_id,
            )
            self.assertEqual(add_assets_to_event(db, event_id, [phone_asset, camera_asset]), 2)
            tag_id = create_tag(db, "Family")
            assign_tags(db, [phone_asset, camera_asset], [tag_id])
            person_id = create_person(db, "Charles")
            assign_person(db, [phone_asset], person_id)
            album_id = create_user_collection(db, "Scotland highlights")
            add_to_user_collection(db, album_id, [phone_asset, camera_asset])
            set_review(db, [phone_asset], status="PICKED", rating=4)
            set_review(db, [camera_asset], status="REJECTED")

            rows = list_library_items(db, LibraryQuery(event_id=event_id, include_rejected=True))
            self.assertEqual({row["filename"] for row in rows}, {"phone.jpg", "camera.jpg"})
            self.assertTrue(all(row["inherited_place_names"] == "Edinburgh" for row in rows))
            self.assertEqual([row["filename"] for row in list_library_items(db, LibraryQuery(search="family"))], ["phone.jpg"])
            self.assertEqual([row["filename"] for row in list_library_items(db, LibraryQuery(source_id=camera_source))], [])
            self.assertEqual(
                [row["filename"] for row in list_library_items(db, LibraryQuery(source_id=camera_source, include_rejected=True))],
                ["camera.jpg"],
            )
            set_source_time_offset(db, camera_source, 3600)
            shifted = list_library_items(db, LibraryQuery(source_id=camera_source, include_rejected=True))
            self.assertEqual(shifted[0]["display_captured"], "2026-08-23 11:00:00")
            self.assertEqual(phone_photo.read_bytes(), phone_bytes)
            self.assertEqual(camera_photo.read_bytes(), camera_bytes)
            db.close()
