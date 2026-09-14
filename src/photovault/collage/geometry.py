"""Shared physical-page geometry helpers for collage interchange and rendering."""
from __future__ import annotations

from typing import Any

PX_PER_MM = 4


def mm_to_px(value: float | int) -> int:
    return round(float(value) * PX_PER_MM)


def px_to_mm(value: float | int) -> float:
    return float(value) / PX_PER_MM


def page_dimensions_mm(page: dict[str, Any]) -> tuple[float, float]:
    width = float(page.get("width_mm", 300))
    height = float(page.get("height_mm", 300))
    if page.get("type") == "spread":
        width *= 2
    return width, height


def page_dimensions_px(page: dict[str, Any]) -> tuple[int, int]:
    width, height = page_dimensions_mm(page)
    return mm_to_px(width), mm_to_px(height)
