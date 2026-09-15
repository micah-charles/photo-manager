from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photovault.catalog.library import LibraryQuery, list_library_items
from photovault.catalog.organization import add_assets_to_event, create_event
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity
from photovault.web.culling import _raw_embedded_jpeg, photo_page, preview


class _Provider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "raw-pairing-volume", "RAW pairing test volume")


class RawJpegPairingRegressionTests(unittest.TestCase):
    def test_matching_raw_is_hidden_but_jpeg_advertises_companion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "photos"
            root.mkdir()
            Image.new("RGB", (64, 48), (30, 80, 120)).save(root / "DSC_0001.JPG")
            # The RAW contents are irrelevant to pairing; the catalog location
            # is inserted below to model a scanned camera RAW asset.
            (root / "DSC_0001.NEF").write_bytes(b"raw")
            db = connect(Path(directory) / "catalog.db")
            self.addCleanup(db.close)
            volume_id = register_volume(db, root, _Provider())
            scan_volume(db, volume_id, root)
            jpeg_id = db.execute("SELECT asset_id FROM asset_locations WHERE filename='DSC_0001.JPG'").fetchone()[0]
            raw_id = db.execute("SELECT asset_id FROM asset_locations WHERE filename='DSC_0001.NEF'").fetchone()[0]
            topic_id = create_event(db, "RAW pairing")
            add_assets_to_event(db, topic_id, [jpeg_id, raw_id])

            rows = list_library_items(db, LibraryQuery(include_rejected=True))
            self.assertEqual([row["filename"] for row in rows], ["DSC_0001.JPG"])
            self.assertEqual(rows[0]["paired_raw_asset_id"], raw_id)
            self.assertEqual(photo_page(db, topic_id)["total"], 1)
            self.assertEqual(photo_page(db, topic_id)["items"][0]["filename"], "DSC_0001.JPG")
            self.assertTrue(photo_page(db, topic_id)["items"][0]["contains_raw"])

    def test_raw_preview_uses_full_embedded_jpeg_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "photos"
            root.mkdir()
            raw_path = root / "only-raw.NEF"
            raw_path.write_bytes(b"raw")
            db = connect(Path(directory) / "catalog.db")
            self.addCleanup(db.close)
            volume_id = register_volume(db, root, _Provider())
            raw_id = "asset_only_raw"
            db.execute("INSERT INTO assets(id, media_type, created_at, updated_at) VALUES (?, 'IMAGE', datetime('now'), datetime('now'))", (raw_id,))
            db.execute("INSERT INTO asset_locations(asset_id, volume_id, relative_path, filename, size_bytes, modified_ns, source_id) VALUES (?, ?, ?, ?, ?, ?, ?)", (raw_id, volume_id, "only-raw.NEF", raw_path.name, raw_path.stat().st_size, raw_path.stat().st_mtime_ns, None))
            db.commit()

            embedded = io.BytesIO()
            Image.new("RGB", (640, 480), (220, 30, 40)).save(embedded, format="JPEG")
            with patch("photovault.web.culling._raw_embedded_jpeg", return_value=embedded.getvalue()):
                result = preview(db, raw_id)
            with Image.open(io.BytesIO(result)) as image:
                self.assertEqual(image.size, (640, 480))

    def test_raw_extractor_prefers_jpg_from_raw(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "photo.NEF"
            path.write_bytes(b"raw")
            completed = type("Completed", (), {"returncode": 0, "stdout": b"full-jpeg"})()
            with patch("photovault.web.culling.shutil.which", return_value="/usr/bin/exiftool"), patch("photovault.web.culling.subprocess.run", return_value=completed) as run:
                self.assertEqual(_raw_embedded_jpeg(path), b"full-jpeg")
            self.assertEqual(run.call_args.args[0][4], "-JpgFromRaw")


if __name__ == "__main__":
    unittest.main()
