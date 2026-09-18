"""Validation helpers for the transparent-slot AI collage package extension.

The normal AI design package is coordinate based and remains unchanged.  This
module adds the optional ``layered-template`` capability: a package may carry
an RGBA foreground, an optional background, and one alpha mask per photo slot.
The importer normalises masks to alpha-only PNGs before they reach Fabric so
the browser and the high-resolution export use the same clipping semantics.
"""
from __future__ import annotations

import io
import math
from copy import deepcopy
from typing import Any

from PIL import Image, ImageChops, ImageDraw

from .design_formats import PHOTO_ROLES
from .geometry import page_dimensions_mm

CAPABILITY = "layered-template"
TRANSPARENT_SLOT_CAPABILITY = "transparent-photo-slots"
MAX_TEMPLATE_PIXELS = 80_000_000
MAX_TEMPLATE_SLOTS = 200


def _safe_template_path(value: Any, names: set[str], label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} must be a relative template path")
    parts = value.split("/")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{label} contains an unsafe template path")
    if not value.startswith("template/") or value not in names:
        raise ValueError(f"{label} is missing from the ZIP: {value}")
    if not value.lower().endswith(".png"):
        raise ValueError(f"{label} must be a PNG file")
    return value


def _image(raw: bytes, path: str, *, require_rgba: bool = False) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (OSError, ValueError) as exc:
        raise ValueError(f"template image is unreadable: {path}") from exc
    if image.format != "PNG":
        raise ValueError(f"template image must be PNG: {path}")
    if image.width < 1 or image.height < 1 or image.width * image.height > MAX_TEMPLATE_PIXELS:
        raise ValueError(f"template image dimensions are too large: {path}")
    if require_rgba and image.mode != "RGBA":
        raise ValueError(f"foreground must be an RGBA PNG with transparency: {path}")
    return image


def _slot_rect(slot: dict[str, Any], page: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return a slot rectangle in page-relative mm.

    The template contract uses the same mm coordinate system as the regular
    design spec.  A compact ``rect_mm`` spelling is accepted as a convenience
    for generated packages, while the canonical fields stay x_mm/y_mm/etc.
    """
    rect = slot.get("rect_mm") if isinstance(slot.get("rect_mm"), dict) else slot
    values = [rect.get(key) for key in ("x_mm", "y_mm", "width_mm", "height_mm")]
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) for value in values):
        raise ValueError("every layered template slot needs finite x_mm, y_mm, width_mm and height_mm")
    x, y, width, height = (float(value) for value in values)
    page_width, page_height = page_dimensions_mm(page)
    if width <= 0 or height <= 0 or x < -float(page.get("bleed_mm", 3)) or y < -float(page.get("bleed_mm", 3)):
        raise ValueError("layered template slot geometry is invalid")
    if x + width > page_width + float(page.get("bleed_mm", 3)) or y + height > page_height + float(page.get("bleed_mm", 3)):
        raise ValueError("layered template slot geometry exceeds the page bleed")
    return x, y, width, height


def _allowed_occlusion_fraction(slot: dict[str, Any], mask: Image.Image) -> tuple[float, Image.Image]:
    """Return the permitted opaque fraction and the slot pixels to inspect."""
    allowed = slot.get("allowedForegroundOcclusion", slot.get("allowed_foreground_occlusion"))
    permitted = 0.0
    inspection = mask.convert("L").point(lambda value: 255 if value > 16 else 0)
    if isinstance(allowed, dict):
        permitted = float(allowed.get("max_fraction", allowed.get("maxFraction", 0)) or 0)
        if not 0 <= permitted <= 1:
            raise ValueError("allowedForegroundOcclusion.max_fraction must be between 0 and 1")
        regions = allowed.get("regions") or []
        if regions:
            # The declared regions are local normalised rectangles.  Remove
            # them from the aperture sample because intentional foreground
            # occlusion must be explicit rather than silently tolerated.
            local = Image.new("L", inspection.size, 0)
            for region in regions:
                if not isinstance(region, dict):
                    raise ValueError("allowed foreground occlusion regions must be objects")
                x = max(0, min(1, float(region.get("x", 0))))
                y = max(0, min(1, float(region.get("y", 0))))
                width = max(0, min(1 - x, float(region.get("width", 0))))
                height = max(0, min(1 - y, float(region.get("height", 0))))
                draw = Image.new("L", inspection.size, 0)
                ImageDraw.Draw(draw).rectangle((round(x * inspection.width), round(y * inspection.height), round((x + width) * inspection.width), round((y + height) * inspection.height)), fill=255)
                local = ImageChops.lighter(local, draw)
            # Keep aperture pixels outside the intentional occlusion regions.
            inspection = ImageChops.subtract(inspection, local)
    return permitted, inspection


def _validate_aperture(foreground: Image.Image, mask: Image.Image, slot_id: str, slot: dict[str, Any]) -> None:
    aperture = mask.convert("L").point(lambda value: 255 if value > 16 else 0)
    if sum(aperture.histogram()[1:]) == 0:
        raise ValueError(f"layered template slot {slot_id} mask has no visible aperture")
    permitted, inspected_mask = _allowed_occlusion_fraction(slot, aperture)
    inspected_count = sum(inspected_mask.histogram()[1:])
    if not inspected_count:
        return
    opaque = ImageChops.multiply(inspected_mask, foreground.getchannel("A").point(lambda value: 255 if value >= 250 else 0))
    opaque_fraction = sum(opaque.histogram()[1:]) / inspected_count
    if opaque_fraction > max(0.01, permitted):
        raise ValueError(
            f"foreground aperture {slot_id} is opaque across {opaque_fraction:.1%} of its photo area; "
            "export a transparent RGBA foreground or declare intentional occlusion"
        )


def _alpha_mask(raw: bytes, path: str, size: tuple[int, int]) -> bytes:
    image = _image(raw, path)
    if image.size != size:
        raise ValueError(f"template mask dimensions do not match foreground: {path}")
    # The interchange contract is white=photo visible / black=clipped. Fabric
    # clips by alpha, not luminance, so normalise luminance into an alpha-only
    # RGBA PNG while keeping the source mask semantics explicit.
    result = Image.new("RGBA", size, (255, 255, 255, 0))
    result.putalpha(image.convert("L"))
    output = io.BytesIO()
    result.save(output, format="PNG", optimize=True)
    return output.getvalue()


def validate_layered_template(manifest: dict[str, Any], design: dict[str, Any], archive: Any, names: set[str]) -> dict[str, Any] | None:
    """Validate and normalise a layered template, returning bytes to cache.

    ``None`` means the ordinary v2 package path should be used unchanged.
    """
    capabilities = manifest.get("capabilities") or []
    template = manifest.get("template")
    if CAPABILITY not in capabilities and not isinstance(template, dict):
        return None
    if not isinstance(capabilities, list) or CAPABILITY not in capabilities or TRANSPARENT_SLOT_CAPABILITY not in capabilities:
        raise ValueError("layered packages must declare layered-template and transparent-photo-slots capabilities")
    if not isinstance(template, dict):
        raise ValueError("layered package manifest.template must be an object")
    page = design.get("page_spec") or manifest.get("page_spec")
    if not isinstance(page, dict):
        raise ValueError("layered package needs page_spec")
    foreground_path = _safe_template_path(template.get("foreground"), names, "template.foreground")
    background_path = template.get("background")
    if background_path is not None:
        background_path = _safe_template_path(background_path, names, "template.background")
    foreground_raw = archive.read(foreground_path)
    foreground = _image(foreground_raw, foreground_path, require_rgba=True)
    page_width, page_height = page_dimensions_mm(page)
    if abs((foreground.width / foreground.height) - (page_width / page_height)) > 0.01:
        raise ValueError("template foreground aspect ratio does not match page_spec")
    background_raw = archive.read(background_path) if background_path else None
    if background_raw is not None:
        background = _image(background_raw, background_path)
        if background.size != foreground.size:
            raise ValueError("template background dimensions must match foreground")
    masks = template.get("masks")
    slots = template.get("slots")
    if not isinstance(masks, dict) or not masks:
        raise ValueError("layered package needs a template.masks map")
    if not isinstance(slots, dict) or not slots or len(slots) > MAX_TEMPLATE_SLOTS:
        raise ValueError("layered package needs a non-empty template.slots map")
    if set(masks) != set(slots):
        raise ValueError("template.masks and template.slots must declare the same slot IDs")
    normalised_slots: dict[str, Any] = {}
    mask_files: dict[str, bytes] = {}
    for slot_id, raw_slot in slots.items():
        if not isinstance(slot_id, str) or not slot_id or len(slot_id) > 32 or not isinstance(raw_slot, dict):
            raise ValueError("layered template slot IDs and definitions are invalid")
        role = str(raw_slot.get("role", "supporting"))
        if role not in PHOTO_ROLES:
            raise ValueError(f"unsupported layered template role for {slot_id}")
        _slot_rect(raw_slot, page)
        mask_path = _safe_template_path(masks[slot_id], names, f"template.masks.{slot_id}")
        mask_raw = archive.read(mask_path)
        mask = _image(mask_raw, mask_path)
        if mask.size != foreground.size:
            raise ValueError(f"template mask dimensions do not match foreground: {slot_id}")
        _validate_aperture(foreground, mask, slot_id, raw_slot)
        normalised_mask = _alpha_mask(mask_raw, mask_path, foreground.size)
        mask_files[mask_path] = normalised_mask
        normalised_slots[slot_id] = {
            **deepcopy(raw_slot),
            "role": role,
            "mask_path": mask_path,
        }
    template_meta = {
        "version": 1,
        "canvas_width_px": foreground.width,
        "canvas_height_px": foreground.height,
        "foreground_path": foreground_path,
        "background_path": background_path,
        "masks": {slot_id: normalised_slots[slot_id]["mask_path"] for slot_id in normalised_slots},
        "slots": normalised_slots,
        "alpha_contract": "white-or-alpha-visible-photo; black-or-alpha-zero-clipped",
    }
    return {
        "template": template_meta,
        "files": {foreground_path: foreground_raw, **({background_path: background_raw} if background_path else {}), **mask_files},
    }
