"""Optional local image classification, stored as derived catalog annotations."""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ImageCategory:
    label: str
    score: float


class ImageClassifier(Protocol):
    model_name: str

    def classify(self, path: Path, top_k: int) -> list[ImageCategory]: ...


class ClassificationCancelled(Exception):
    """Raised when a user stops a rebuildable enrichment pass."""


class OnnxImageNetClassifier:
    """Local ONNX ImageNet classifier with explicit labels and preprocessing."""

    def __init__(self, model_path: Path, labels_path: Path, model_name: str | None = None, image_size: int = 224) -> None:
        try:
            import numpy as np
            import onnxruntime as ort
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - optional backend
            raise RuntimeError("install the 'ml' extra to use local ONNX classification") from exc
        labels = [label.strip() for label in labels_path.read_text(encoding="utf-8").splitlines() if label.strip()]
        if not labels:
            raise ValueError("classification labels file is empty")
        self._np, self._image = np, Image
        # CoreML is a useful optional macOS acceleration provider, but some
        # sandboxed or managed environments forbid its system cache directory.
        # CPU is always a correct portable fallback (and the Windows path).
        try:
            self._session = ort.InferenceSession(str(model_path), providers=["CoreMLExecutionProvider", "CPUExecutionProvider"])
        except Exception:
            self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        inputs, outputs = self._session.get_inputs(), self._session.get_outputs()
        if len(inputs) != 1 or not outputs:
            raise ValueError("ONNX classifier must expose one image input and at least one output")
        shape = inputs[0].shape
        if len(shape) != 4 or (isinstance(shape[1], int) and shape[1] != 3):
            raise ValueError("ONNX classifier input must be NCHW RGB")
        if isinstance(shape[2], int) and isinstance(shape[3], int) and (shape[2] != image_size or shape[3] != image_size):
            raise ValueError(f"ONNX classifier expects {shape[2]}x{shape[3]}; pass that image_size")
        self._input_name, self._output_name = inputs[0].name, outputs[0].name
        self._labels, self.image_size = labels, image_size
        self.model_name = model_name or model_path.stem
        self._mean = np.asarray((0.485, 0.456, 0.406), dtype=np.float32).reshape(1, 3, 1, 1)
        self._std = np.asarray((0.229, 0.224, 0.225), dtype=np.float32).reshape(1, 3, 1, 1)

    def classify(self, path: Path, top_k: int = 5) -> list[ImageCategory]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        with self._image.open(path) as image:
            image = image.convert("RGB").resize((self.image_size, self.image_size), self._image.Resampling.LANCZOS)
            array = self._np.asarray(image, dtype=self._np.float32).transpose(2, 0, 1)[None, ...] / 255.0
        logits = self._np.asarray(self._session.run([self._output_name], {self._input_name: (array - self._mean) / self._std})[0], dtype=self._np.float32).reshape(-1)
        if logits.size != len(self._labels) or not self._np.isfinite(logits).all():
            raise ValueError(f"classifier output has {logits.size} values; expected {len(self._labels)} labels")
        logits -= logits.max(); probabilities = self._np.exp(logits); probabilities /= probabilities.sum()
        indices = self._np.argsort(probabilities)[::-1][:top_k]
        return [ImageCategory(self._labels[int(index)], float(probabilities[int(index)])) for index in indices]


def index_image_categories(
    connection: sqlite3.Connection,
    classifier: ImageClassifier,
    volume_id: str | None = None,
    limit: int = 0,
    top_k: int = 5,
    commit_every: int = 25,
    offset: int = 0,
    progress_callback=None,
    cancel_callback=None,
) -> dict[str, int]:
    """Classify connected images only; originals remain untouched and hash-invalidated."""
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if commit_every < 1:
        raise ValueError("commit_every must be positive")
    if offset < 0:
        raise ValueError("offset must not be negative")
    sql = """SELECT al.asset_id, v.current_mount_path, al.relative_path, eh.sha256
             FROM asset_locations al JOIN assets a ON a.id=al.asset_id JOIN volumes v ON v.id=al.volume_id
             JOIN exact_hashes eh ON eh.asset_id=al.asset_id
             WHERE al.missing_since IS NULL AND a.media_type='IMAGE' AND v.status='CONNECTED' AND v.current_mount_path IS NOT NULL"""
    params: list[object] = []
    if volume_id:
        sql += " AND v.id=?"; params.append(volume_id)
    representatives: dict[str, tuple[Path, str]] = {}
    for asset_id, mount, relative_path, sha256 in connection.execute(sql + " ORDER BY al.asset_id, al.id", params):
        representatives.setdefault(str(asset_id), (Path(str(mount)) / str(relative_path), str(sha256)))
    candidates = list(representatives.items())
    if limit > 0:
        candidates = candidates[offset : offset + limit]
    elif offset:
        candidates = candidates[offset:]
    representatives = dict(candidates)
    indexed = skipped = errors = 0; now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    processed_since_commit = 0
    for asset_id, (path, sha256) in representatives.items():
        if cancel_callback is not None and cancel_callback():
            raise ClassificationCancelled("category analysis cancelled")
        current = connection.execute("SELECT COUNT(*), MIN(source_sha256), MAX(source_sha256) FROM image_categories WHERE asset_id=? AND model=?", (asset_id, classifier.model_name)).fetchone()
        if current[0] and current[1] == sha256 and current[2] == sha256:
            skipped += 1
            if progress_callback is not None:
                progress_callback({"processed": indexed + skipped + errors, "assets": len(representatives), "indexed": indexed, "skipped": skipped, "errors": errors})
            continue
        try:
            categories = classifier.classify(path, top_k)
            if not categories or any(not item.label or not math.isfinite(item.score) or not 0 <= item.score <= 1 for item in categories):
                raise ValueError("classifier returned invalid categories")
            connection.execute("DELETE FROM image_categories WHERE asset_id=? AND model=?", (asset_id, classifier.model_name))
            connection.executemany(
                "INSERT INTO image_categories(asset_id, model, label, score, source_sha256, computed_at) VALUES (?, ?, ?, ?, ?, ?)",
                ((asset_id, classifier.model_name, item.label, item.score, sha256, now) for item in categories),
            )
            indexed += 1
        except Exception:
            # A damaged or unsupported image must not abandon a long-running
            # derived-data pass.  The source bytes are never changed.
            errors += 1
        processed_since_commit += 1
        if processed_since_commit >= commit_every:
            connection.commit()
            processed_since_commit = 0
        if progress_callback is not None:
            progress_callback({"processed": indexed + skipped + errors, "assets": len(representatives), "indexed": indexed, "skipped": skipped, "errors": errors})
    connection.commit()
    return {"indexed": indexed, "skipped": skipped, "errors": errors, "assets": len(representatives)}
