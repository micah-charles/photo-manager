from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Canvas:
    width: int = 1200
    height: int = 800
    gutter: int = 12


@dataclass(frozen=True)
class PageSpec:
    """Physical page intent; preview pixels are derived, never authoritative."""

    type: str = "single"
    width_mm: float = 300.0
    height_mm: float = 300.0
    orientation: str = "square"
    bleed_mm: float = 3.0
    safe_margin_mm: float = 8.0
    gutter_mm: float = 4.0
    dpi: int = 300
    background: str = "#f5f2ed"
    preset_id: str = "large-square"

    def to_preview_canvas(self, long_edge: int = 1200) -> Canvas:
        page_width_mm = self.width_mm * (2 if self.type == "spread" else 1)
        long_dimension = max(page_width_mm, self.height_mm)
        width = max(1, round(page_width_mm / long_dimension * long_edge))
        height = max(1, round(self.height_mm / long_dimension * long_edge))
        if page_width_mm >= self.height_mm:
            width, height = long_edge, height
        else:
            width, height = width, long_edge
        return Canvas(width=width, height=height, gutter=max(1, round(self.gutter_mm / page_width_mm * width)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PAGE_PRESETS: dict[str, PageSpec] = {
    "small-square": PageSpec(width_mm=200, height_mm=200, preset_id="small-square"),
    "square": PageSpec(width_mm=250, height_mm=250, preset_id="square"),
    "large-square": PageSpec(width_mm=300, height_mm=300, preset_id="large-square"),
    "a4-portrait": PageSpec(width_mm=210, height_mm=297, orientation="portrait", preset_id="a4-portrait"),
    "a4-landscape": PageSpec(width_mm=297, height_mm=210, orientation="landscape", preset_id="a4-landscape"),
    "large-landscape": PageSpec(width_mm=300, height_mm=200, orientation="landscape", preset_id="large-landscape"),
    "large-portrait": PageSpec(width_mm=200, height_mm=300, orientation="portrait", preset_id="large-portrait"),
}


def page_spec_from_dict(payload: dict[str, Any] | None) -> PageSpec:
    values = dict(payload or {})
    preset_id = str(values.get("preset_id") or "large-square")
    base = PAGE_PRESETS.get(preset_id, PAGE_PRESETS["large-square"])
    allowed = {item.name for item in fields(PageSpec)}
    values = {key: value for key, value in values.items() if key in allowed}
    return PageSpec(**{**base.to_dict(), **values})


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
    transform: dict[str, Any] = field(default_factory=lambda: {"zoom": 1.0, "pan_x": 0.0, "pan_y": 0.0, "rotation": 0.0})


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
    page_spec: dict[str, Any] = field(default_factory=lambda: PageSpec().to_dict())

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
