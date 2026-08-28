from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from photovault.catalog.scanner import register_volume, scan_volume
from photovault.catalog.semantic import _validate_image_input_shape, index_embeddings, search_embeddings
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity

class FixedProvider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test_uuid", "semantic-disk", "semantic-disk")

class FakeEngine:
    model_name = "test-model"
    def __init__(self) -> None: self.calls = 0
    def embed(self, path: Path) -> list[float]:
        self.calls += 1
        return [1.0, 0.0] if path.name == "a.jpg" else [0.0, 1.0]

class SemanticTests(unittest.TestCase):
    def test_onnx_image_shape_validation_rejects_text_models(self) -> None:
        with self.assertRaisesRegex(ValueError, "rank-4 NCHW"):
            _validate_image_input_shape([None, 77], 224)
        with self.assertRaisesRegex(ValueError, "3 RGB channels"):
            _validate_image_input_shape([None, 1, 224, 224], 224)

    def test_embedding_index_is_hash_cached_and_searches_cosine_similarity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "photos"; root.mkdir()
            (root / "a.jpg").write_bytes(b"a"); (root / "b.jpg").write_bytes(b"b")
            db = connect(Path(temp) / "catalog.db")
            volume_id = register_volume(db, root, FixedProvider()); scan_volume(db, volume_id, root)
            engine = FakeEngine()
            self.assertEqual(index_embeddings(db, engine)["indexed"], 2)
            self.assertEqual(index_embeddings(db, engine)["skipped"], 2)
            self.assertEqual(engine.calls, 2)
            expected = db.execute("SELECT asset_id FROM asset_locations WHERE filename='a.jpg'").fetchone()[0]
            self.assertEqual(search_embeddings(db, "test-model", [1.0, 0.0], 1)[0][0], expected)

    def test_embedding_index_limit_is_an_asset_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "photos"; root.mkdir()
            for name in ("a.jpg", "b.jpg"):
                (root / name).write_bytes(name.encode())
            db = connect(Path(temp) / "catalog.db")
            volume_id = register_volume(db, root, FixedProvider()); scan_volume(db, volume_id, root)
            result = index_embeddings(db, FakeEngine(), limit=1)
            self.assertEqual(result["assets"], 1)
            self.assertEqual(result["indexed"], 1)

if __name__ == "__main__": unittest.main()
