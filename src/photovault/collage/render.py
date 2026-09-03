from __future__ import annotations

import json
from pathlib import Path

from .models import LayoutCandidate, PhotoInput

try:
    from PIL import Image, ImageDraw, ImageOps
except ImportError:  # pragma: no cover
    Image = ImageDraw = ImageOps = None


def render_candidate(candidate: LayoutCandidate, photos: dict[str, PhotoInput], destination: Path, smart_crop: bool = True) -> Path:
    if Image is None:
        raise RuntimeError("Pillow is required for rendering the collage POC")
    canvas = Image.new("RGB", (candidate.canvas.width, candidate.canvas.height), (245, 242, 237))
    for cell in candidate.cells:
        with Image.open(photos[cell.photo_id].path) as source:
            crop = cell.crop
            if not smart_crop and cell.crop_metadata.get("raw_center_crop"):
                crop = cell.crop_metadata["raw_center_crop"]
            if isinstance(crop, dict):
                from .models import Crop
                crop = Crop(**crop)
            image = ImageOps.fit(source.convert("RGB"), (cell.width, cell.height), method=Image.Resampling.LANCZOS, centering=((crop.left + crop.right) / 2, (crop.top + crop.bottom) / 2))
            canvas.paste(image, (cell.x, cell.y))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="JPEG", quality=88, optimize=True)
    return destination


def write_crop_comparison_sheet(items, photos: dict[str, PhotoInput], destination: Path, columns: int = 3) -> Path:
    """Render one naive-vs-smart strip per candidate for Phase 2 debugging."""
    if Image is None:
        raise RuntimeError("Pillow is required for crop comparison sheets")
    tile_w, tile_h, label_h = 420, 230, 30
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_w, rows * (tile_h + label_h)), (230, 226, 220))
    draw = ImageDraw.Draw(sheet)
    for index, candidate in enumerate(items):
        x, y = (index % columns) * tile_w, (index // columns) * (tile_h + label_h)
        strip = Image.new("RGB", (tile_w - 8, tile_h), (245, 242, 237))
        for smart, offset in ((False, 0), (True, (tile_w - 8) // 2)):
            panel = Image.new("RGB", ((tile_w - 8) // 2, tile_h), (245, 242, 237))
            for cell in candidate.cells:
                with Image.open(photos[cell.photo_id].path) as source:
                    crop = cell.crop if smart else cell.crop_metadata.get("raw_center_crop", cell.crop)
                    if isinstance(crop, dict):
                        from .models import Crop
                        crop = Crop(**crop)
                    image = ImageOps.fit(source.convert("RGB"), (max(1, cell.width // 6), max(1, cell.height // 6)), method=Image.Resampling.LANCZOS, centering=((crop.left + crop.right) / 2, (crop.top + crop.bottom) / 2))
                    panel.paste(image, (cell.x // 6, cell.y // 6))
            strip.paste(panel, (offset, 0))
        sheet.paste(strip, (x + 4, y))
        draw.text((x + 8, y + tile_h + 6), f"{candidate.provider} #{candidate.candidate_number} · BEFORE → AFTER", fill=(30, 28, 25))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="JPEG", quality=90)
    return destination


def write_contact_sheet(items: list[tuple[LayoutCandidate, Path]], destination: Path, columns: int = 4) -> Path:
    if Image is None:
        raise RuntimeError("Pillow is required for contact sheets")
    tile_w, tile_h, label_h = 300, 220, 28
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_w, rows * (tile_h + label_h)), (230, 226, 220))
    draw = ImageDraw.Draw(sheet)
    for index, (candidate, path) in enumerate(items):
        x, y = (index % columns) * tile_w, (index // columns) * (tile_h + label_h)
        with Image.open(path) as image:
            image.thumbnail((tile_w - 8, tile_h - 8))
            sheet.paste(image, (x + (tile_w - image.width) // 2, y + (tile_h - image.height) // 2))
        draw.text((x + 6, y + tile_h + 5), f"{candidate.provider} #{candidate.candidate_number} · seed {candidate.seed}", fill=(30, 28, 25))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="JPEG", quality=90)
    return destination


def write_metadata(candidates: list[LayoutCandidate], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps([candidate.to_dict() for candidate in candidates], indent=2, default=str), encoding="utf-8")
    return destination
