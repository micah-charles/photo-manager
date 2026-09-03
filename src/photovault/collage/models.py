from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Canvas:
    width: int = 1200
    height: int = 800
    gutter: int = 12


@dataclass(frozen=True)
class PhotoInput:
    photo_id: str
    path: Path
    width: int
    height: int
    capture_datetime: str | None = None
    quality_score: float = 0.0
    analysis: Any | None = None

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height else 1.0


@dataclass(frozen=True)
class Crop:
    left: float
    top: float
    right: float
    bottom: float
    mode: str = "cover"


@dataclass(frozen=True)
class Cell:
    photo_id: str
    x: int
    y: int
    width: int
    height: int
    crop: Crop
    crop_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LayoutCandidate:
    provider: str
    candidate_number: int
    seed: int
    canvas: Canvas
    cells: list[Cell]
    style: str = ""
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    rejected: bool = False
    rejection_reasons: list[str] = field(default_factory=list)
    # Provider-neutral editable-document identity. The rendered preview is
    # disposable; this structured candidate remains the source of truth.
    document_id: str = ""
    source_run_id: str = ""
    parent_candidate_id: str | None = None
    edited: bool = False
    created_at: str | None = None
    modified_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def frames(self) -> list[Cell]:
        """Alias used by the editor and the provider-neutral document model."""
        return self.cells

    def to_document(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload["document_type"] = "CollageDocument"
        payload["frames"] = payload["cells"]
        return payload
