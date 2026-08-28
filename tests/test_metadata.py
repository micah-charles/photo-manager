from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

from photovault.catalog.scanner import register_volume, scan_volume
from photovault.catalog.gallery import write_gallery
from photovault.catalog.timeline import list_timeline
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test_uuid", "metadata-disk", "metadata-disk")


class MetadataTests(unittest.TestCase):
    def test_exif_dimensions_thumbnail_and_timeline_are_catalogued(self) -> None:
        if Image is None:
            self.skipTest("Pillow is not installed")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "photos"
            root.mkdir()
            source = root / "photo.jpg"
            exif = Image.Exif()
            exif[306] = "2024:01:02 03:04:05"
            exif[271] = "Test Camera Co"
            exif[272] = "Model X"
            exif[274] = 1
            Image.new("RGB", (640, 480), "red").save(source, exif=exif)
            db = connect(Path(temp) / "catalog.db")
            volume_id = register_volume(db, root, FixedProvider())
            thumbnail_root = Path(temp) / "thumbnails"
            scan_volume(db, volume_id, root, thumbnail_root)
            metadata = db.execute(
                "SELECT capture_datetime, camera_make, camera_model, width, height FROM media_metadata"
            ).fetchone()
            self.assertEqual(tuple(metadata), ("2024-01-02T03:04:05", "Test Camera Co", "Model X", 640, 480))
            thumbnail = db.execute("SELECT path, width, height FROM thumbnails").fetchone()
            self.assertTrue(Path(thumbnail[0]).exists())
            self.assertEqual(tuple(thumbnail[1:]), (320, 240))
            timeline = list_timeline(db, volume_id, 10)
            self.assertEqual(timeline[0][1], "photo.jpg")
            self.assertEqual(timeline[0][4], "2024-01-02T03:04:05")
            gallery = write_gallery(db, Path(temp) / "gallery" / "index.html", volume_id)
            self.assertTrue(gallery.exists())
            gallery_html = gallery.read_text(encoding="utf-8")
            self.assertIn("photo.jpg", gallery_html)
            self.assertIn("PhotoVault Gallery", gallery_html)

    def test_video_catalogues_without_thumbnail_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            (root / "clip.mp4").write_bytes(b"not-a-real-video")
            db = connect(Path(temp) / "catalog.db")
            volume_id = register_volume(db, root, FixedProvider())
            result = scan_volume(db, volume_id, root, Path(temp) / "thumbs")
            self.assertEqual(result["files_catalogued"], 1)
            self.assertEqual(db.execute("SELECT media_type FROM assets").fetchone()[0], "VIDEO")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM thumbnails").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
