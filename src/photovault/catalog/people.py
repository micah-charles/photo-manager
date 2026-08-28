from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class FaceObservation:
    """Platform-neutral face result; coordinates are normalized 0..1."""
    left: float
    top: float
    right: float
    bottom: float
    embedding: tuple[float, ...] | None = None


class FaceEngine(Protocol):
    def detect(self, path: Path) -> list[FaceObservation]: ...


class UnavailableFaceEngine:
    """Explicit no-op until a macOS Vision or ONNX engine is installed."""
    def detect(self, path: Path) -> list[FaceObservation]:
        return []
