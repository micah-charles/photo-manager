from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

class EmbeddingEngine(Protocol):
    model_name: str
    def embed(self, path: Path) -> list[float]: ...


def _validate_image_input_shape(input_shape: list[object], image_size: int) -> None:
    if len(input_shape) != 4:
        raise ValueError("ONNX image model input must be rank-4 NCHW")
    channels, height, width = input_shape[1:]
    if isinstance(channels, int) and channels != 3:
        raise ValueError(f"ONNX image model must accept 3 RGB channels, got {channels}")
    if isinstance(height, int) and isinstance(width, int) and (height != image_size or width != image_size):
        raise ValueError(f"ONNX image model expects {height}x{width}; pass --image-size {height}")


class OnnxEmbeddingEngine:
    """Optional local ONNX image encoder.

    The model file is supplied by the user; PhotoVault never downloads model
    weights. The default preprocessing matches common NCHW RGB image models,
    while ``mean``/``std`` and ``image_size`` can be adjusted for a specific
    exported CLIP/vision encoder.
    """

    def __init__(self, model_path: Path, model_name: str | None = None,
                 image_size: int = 224, mean: tuple[float, float, float] = (0.485, 0.456, 0.406),
                 std: tuple[float, float, float] = (0.229, 0.224, 0.225)) -> None:
        try:
            import numpy as np
            import onnxruntime as ort
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - optional ML backend
            raise RuntimeError("install the 'ml' extra to use OnnxEmbeddingEngine") from exc
        if image_size <= 0:
            raise ValueError("image_size must be positive")
        self._np = np
        self._image = Image
        self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        if not inputs or not outputs:
            raise ValueError("ONNX model must expose at least one input and output")
        _validate_image_input_shape(inputs[0].shape, image_size)
        self._input_name = inputs[0].name
        self._output_name = outputs[0].name
        self.model_name = model_name or model_path.stem
        self.image_size = image_size
        self.mean = np.asarray(mean, dtype=np.float32).reshape(1, 3, 1, 1)
        self.std = np.asarray(std, dtype=np.float32).reshape(1, 3, 1, 1)

    def embed(self, path: Path) -> list[float]:
        with self._image.open(path) as image:
            image = image.convert("RGB").resize((self.image_size, self.image_size), self._image.Resampling.LANCZOS)
            array = self._np.asarray(image, dtype=self._np.float32) / 255.0
        array = array.transpose(2, 0, 1)[None, ...]
        array = (array - self.mean) / self.std
        output = self._session.run([self._output_name], {self._input_name: array})[0]
        vector = self._np.asarray(output, dtype=self._np.float32).reshape(-1)
        if vector.size == 0 or not self._np.isfinite(vector).all():
            raise ValueError("ONNX model returned an invalid embedding")
        return [float(value) for value in vector]

def index_embeddings(connection: sqlite3.Connection, engine: EmbeddingEngine, volume_id: str | None = None, limit: int = 0) -> dict[str, int]:
    sql = "SELECT al.asset_id, v.current_mount_path, al.relative_path, eh.sha256 FROM asset_locations al JOIN volumes v ON v.id=al.volume_id JOIN exact_hashes eh ON eh.asset_id=al.asset_id WHERE al.missing_since IS NULL AND v.status='CONNECTED' AND v.current_mount_path IS NOT NULL"
    params: tuple[object, ...] = ()
    if volume_id:
        sql += " AND v.id=?"
        params = (volume_id,)
    rows = list(connection.execute(sql + " ORDER BY al.asset_id, v.status DESC, al.id", params))
    seen: set[str] = set(); indexed = skipped = errors = 0
    for row in rows:
        asset_id = row[0]
        if asset_id in seen: continue
        if limit > 0 and len(seen) >= limit: break
        seen.add(asset_id)
        current = connection.execute("SELECT source_sha256 FROM embeddings WHERE asset_id=? AND model=?", (asset_id, engine.model_name)).fetchone()
        if current is not None and current[0] == row[3]: skipped += 1; continue
        try:
            vector = [float(value) for value in engine.embed(Path(row[1]) / row[2])]
            if not vector or not all(math.isfinite(value) for value in vector): raise ValueError("embedding must be non-empty and finite")
            connection.execute("INSERT INTO embeddings(asset_id, model, vector_json, source_sha256, computed_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(asset_id, model) DO UPDATE SET vector_json=excluded.vector_json, source_sha256=excluded.source_sha256, computed_at=excluded.computed_at", (asset_id, engine.model_name, json.dumps(vector), row[3], datetime.now(timezone.utc).isoformat(timespec="seconds")))
            indexed += 1
        except (OSError, RuntimeError, ValueError): errors += 1
    connection.commit()
    return {"indexed": indexed, "skipped": skipped, "errors": errors, "assets": len(seen)}

def search_embeddings(connection: sqlite3.Connection, model: str, query: list[float], limit: int = 20) -> list[tuple[str, float]]:
    if not query or limit <= 0: return []
    query_norm = math.sqrt(sum(value * value for value in query))
    if query_norm == 0: return []
    results = []
    for row in connection.execute("SELECT asset_id, vector_json FROM embeddings WHERE model=?", (model,)):
        vector = json.loads(row[1]); norm = math.sqrt(sum(value * value for value in vector))
        score = sum(left * right for left, right in zip(query, vector)) / (query_norm * norm) if norm else 0.0
        results.append((row[0], score))
    return sorted(results, key=lambda item: item[1], reverse=True)[:limit]
