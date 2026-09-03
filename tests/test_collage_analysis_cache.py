import tempfile
import unittest
from pathlib import Path

from photovault.collage.analysis import FaceBox, PhotoAnalysis
from photovault.collage.models import PhotoInput
from photovault.web.server import load_collage_analysis_cache, save_collage_analysis_cache


class CollageAnalysisCacheTests(unittest.TestCase):
    def test_round_trip_preserves_asset_id_and_face_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "analysis.json"
            photo = PhotoInput(
                "asset-one", Path(directory) / "photo.jpg", 1200, 800,
                quality_score=12.5,
                analysis=PhotoAnalysis(1200, 800, 1, (FaceBox(.1, .2, .3, .4, .9),), quality_score=12.5),
            )
            fingerprints = {"asset-one": {"path": str(photo.path), "size_bytes": 123, "modified_ns": 456}}
            save_collage_analysis_cache(cache_path, {"asset-one": photo}, fingerprints)
            photos, loaded_fingerprints = load_collage_analysis_cache(cache_path)
            self.assertEqual(photos["asset-one"].photo_id, "asset-one")
            self.assertEqual(photos["asset-one"].analysis.faces[0].right, .3)
            self.assertEqual(loaded_fingerprints, fingerprints)


if __name__ == "__main__":
    unittest.main()
