from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

from photovault.catalog.metadata import _image_metadata
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.catalog.gallery import write_gallery
from photovault.catalog.timeline import list_timeline
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity


class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test_uuid", "metadata-disk", "metadata-disk")


class MetadataTests(unittest.TestCase):
    def test_malformed_gps_value_does_not_abort_image_metadata(self) -> None:
        if Image is None:
            self.skipTest("Pillow is not installed")

        class FakeImage:
            width = 32
            height = 24

            def getexif(self):
                return {34853: 1, 306: "2024:01:02 03:04:05"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch("photovault.catalog.metadata.Image.open", return_value=FakeImage()):
            record = _image_metadata(Path("malformed-gps.jpg"))
        self.assertEqual((record.capture_datetime, record.width, record.height), ("2024-01-02T03:04:05", 32, 24))
        self.assertEqual((record.latitude, record.longitude), (None, None))

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

    def test_gif_is_catalogued_as_image_with_a_cached_thumbnail(self) -> None:
        if Image is None:
            self.skipTest("Pillow is not installed")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            source = root / "animated.gif"
            Image.new("RGB", (48, 36), "green").save(source, format="GIF")
            db = connect(Path(temp) / "catalog.db")
            volume_id = register_volume(db, root, FixedProvider())
            result = scan_volume(db, volume_id, root, Path(temp) / "thumbs")
            self.assertEqual(result["files_catalogued"], 1)
            self.assertEqual(db.execute("SELECT media_type FROM assets").fetchone()[0], "IMAGE")
            thumbnail = db.execute("SELECT path FROM thumbnails").fetchone()[0]
            self.assertTrue(Path(thumbnail).is_file())


if __name__ == "__main__":
    unittest.main()
