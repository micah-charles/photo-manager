from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.favourites import set_favourite
from photovault.catalog.library import LibraryQuery, count_library_items, list_library_items
from photovault.catalog.organization import add_assets_to_event, assign_tags, create_event, create_place, create_tag, set_asset_source, set_review
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "library-volume", "Library volume")


class LibraryTests(unittest.TestCase):
    def test_catalog_query_filters_without_rescanning_or_hiding_offline_media(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; (root / "DCIM/Camera").mkdir(parents=True)
            (root / "DCIM/Camera/cat.jpg").write_bytes(b"cat")
            (root / "DCIM/Camera/clip.mp4").write_bytes(b"video")
            connection = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider())
            scan_volume(connection, volume_id, root)
            cat_asset = connection.execute("SELECT asset_id FROM asset_locations WHERE filename='cat.jpg'").fetchone()[0]
            set_favourite(connection, cat_asset)
            favourites = LibraryQuery(folder_prefix="DCIM/Camera", media_type="IMAGE", favourite_only=True)
            rows = list_library_items(connection, favourites)
            self.assertEqual((len(rows), rows[0]["filename"], rows[0]["is_favourite"]), (1, "cat.jpg", 1))
            self.assertEqual(count_library_items(connection, favourites), 1)
            connection.execute("UPDATE volumes SET status='OFFLINE' WHERE id=?", (volume_id,)); connection.commit()
            offline = list_library_items(connection, LibraryQuery(search="clip"))
            self.assertEqual((offline[0]["filename"], offline[0]["volume_status"]), ("clip.mp4", "OFFLINE"))
            connection.close()

    def test_organisation_filters_share_the_library_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; root.mkdir()
            (root / "phone.jpg").write_bytes(b"phone")
            (root / "camera.jpg").write_bytes(b"camera")
            connection = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider())
            scan_volume(connection, volume_id, root)
            assets = {row["filename"]: row["asset_id"] for row in connection.execute("SELECT filename, asset_id FROM asset_locations")}
            connection.execute(
                """INSERT INTO source_profiles
                   (id, source_id, manufacturer, model, display_name, adapter, first_seen, last_seen, source_type)
                   VALUES ('phone', 'phone-source', 'Google', 'Pixel', 'Pixel phone', 'folder', datetime('now'), datetime('now'), 'android_device')"""
            )
            connection.commit()
            set_asset_source(connection, assets["phone.jpg"], "phone-source")
            event_id = create_event(connection, "Trip")
            add_assets_to_event(connection, event_id, [assets["phone.jpg"]])
            tag_id = create_tag(connection, "Travel")
            assign_tags(connection, [assets["phone.jpg"]], [tag_id])
            set_review(connection, [assets["phone.jpg"]], status="REJECTED", rating=4)
            by_source = list_library_items(connection, LibraryQuery(source_id="phone-source", include_rejected=True))
            self.assertEqual([row["filename"] for row in by_source], ["phone.jpg"])
            self.assertEqual(list_library_items(connection, LibraryQuery(event_id=event_id, include_rejected=True))[0]["filename"], "phone.jpg")
            self.assertEqual(list_library_items(connection, LibraryQuery(tag_id=tag_id, include_rejected=True))[0]["filename"], "phone.jpg")
            self.assertEqual(list_library_items(connection, LibraryQuery(search="travel", include_rejected=True))[0]["filename"], "phone.jpg")
            place_id = create_place(connection, "Edinburgh")
            inherited_event = create_event(connection, "Scotland", default_place_id=place_id)
            add_assets_to_event(connection, inherited_event, [assets["phone.jpg"]])
            self.assertEqual(list_library_items(connection, LibraryQuery(search="edinburgh", include_rejected=True))[0]["filename"], "phone.jpg")
            self.assertEqual(list_library_items(connection, LibraryQuery(search="phone", include_rejected=True))[0]["filename"], "phone.jpg")
            self.assertEqual(list_library_items(connection, LibraryQuery(review_status="REJECTED", include_rejected=True))[0]["filename"], "phone.jpg")
            self.assertEqual(count_library_items(connection, LibraryQuery(review_status="REJECTED", include_rejected=True)), 1)
            connection.close()

    def test_event_default_place_is_explicitly_inherited_without_overwriting_asset_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; root.mkdir()
            (root / "photo.jpg").write_bytes(b"photo")
            connection = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider())
            scan_volume(connection, volume_id, root)
            asset_id = connection.execute("SELECT asset_id FROM asset_locations LIMIT 1").fetchone()[0]
            place_id = create_place(connection, "Edinburgh")
            event_id = create_event(connection, "Scotland trip", default_place_id=place_id)
            add_assets_to_event(connection, event_id, [asset_id])
            rows = list_library_items(connection, LibraryQuery(event_id=event_id, include_rejected=True))
            self.assertEqual(rows[0]["inherited_place_names"], "Edinburgh")
            self.assertIsNone(rows[0]["place_names"])
            self.assertEqual(count_library_items(connection, LibraryQuery(place_id=place_id, include_rejected=True)), 1)
            connection.close()

    def test_recently_added_uses_catalog_time_not_capture_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; root.mkdir()
            (root / "old-capture.jpg").write_bytes(b"old")
            connection = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider())
            scan_volume(connection, volume_id, root)
            asset_id = connection.execute("SELECT asset_id FROM asset_locations LIMIT 1").fetchone()[0]
            connection.execute("UPDATE media_metadata SET capture_datetime=? WHERE asset_id=?", ("2010-01-01T00:00:00", asset_id))
            connection.commit()
            rows = list_library_items(connection, LibraryQuery(recently_added=True))
            self.assertEqual([row["filename"] for row in rows], ["old-capture.jpg"])
            connection.close()

    def test_recently_added_orders_by_catalog_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; root.mkdir()
            (root / "first.jpg").write_bytes(b"first")
            (root / "second.jpg").write_bytes(b"second")
            connection = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider())
            scan_volume(connection, volume_id, root)
            assets = {row["filename"]: row["asset_id"] for row in connection.execute("SELECT filename, asset_id FROM asset_locations")}
            connection.execute("UPDATE assets SET created_at=? WHERE id=?", ("2026-08-30T00:00:00+00:00", assets["first.jpg"]))
            connection.execute("UPDATE assets SET created_at=? WHERE id=?", ("2026-08-31T00:00:00+00:00", assets["second.jpg"]))
            connection.commit()
            rows = list_library_items(connection, LibraryQuery(recently_added=True))
            self.assertEqual([row["filename"] for row in rows], ["second.jpg", "first.jpg"])
            connection.close()

    def test_import_batch_filter_limits_library_to_that_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"; root.mkdir()
            (root / "first.jpg").write_bytes(b"first")
            (root / "second.jpg").write_bytes(b"second")
            connection = connect(Path(directory) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider())
            scan_volume(connection, volume_id, root)
            assets = {row["filename"]: row["asset_id"] for row in connection.execute("SELECT filename, asset_id FROM asset_locations")}
            hashes = {row[0]: row[1] for row in connection.execute("SELECT asset_id, sha256 FROM exact_hashes")}
            source_id = str(connection.execute("SELECT source_id FROM asset_locations LIMIT 1").fetchone()[0])
            connection.executemany(
                "INSERT INTO operations(id, operation_type, created_at, completed_at, status, dry_run) VALUES (?, 'IMPORT', datetime('now'), datetime('now'), 'COMPLETED', 0)",
                (("op-1",), ("op-2",)),
            )
            connection.executemany(
                """INSERT INTO import_batches
                   (id, source_id, destination_volume_id, started_at, completed_at,
                    status, planned_items, imported_items)
                   VALUES (?, ?, ?, datetime('now'), datetime('now'), 'COMPLETED', 1, 1)""",
                (("batch-1", source_id, volume_id), ("batch-2", source_id, volume_id)),
            )
            for filename, batch_id in (("first.jpg", "batch-1"), ("second.jpg", "batch-2")):
                connection.execute(
                    """INSERT INTO source_imports
                       (source_id, logical_path, source_object_id, source_size_bytes,
                        destination_volume_id, destination_relative_path, sha256,
                        operation_id, imported_at, batch_id)
                       VALUES (?, ?, ?, 5, ?, ?, ?, ?, datetime('now'), ?)""",
                    (source_id, filename, filename, volume_id, filename, hashes[assets[filename]], "op-1" if batch_id == "batch-1" else "op-2", batch_id),
                )
            connection.commit()
            rows = list_library_items(connection, LibraryQuery(import_batch_id="batch-1"))
            self.assertEqual([row["filename"] for row in rows], ["first.jpg"])
            self.assertEqual(count_library_items(connection, LibraryQuery(import_batch_id="batch-1")), 1)
            connection.close()
