"""Versioned, safe interchange formats for human-assisted collage design.

The AI-facing format deliberately contains catalog ids, never executable markup or
untrusted local paths.  The server resolves those ids back to the catalog before
creating an editable document.
"""
from __future__ import annotations

import math
import re
import uuid
from copy import deepcopy
from typing import Any

from .geometry import mm_to_px, page_dimensions_mm

HEX = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
MASKS = {"rectangle", "rounded", "circle", "ellipse"}
ROLES = {"hero", "secondary", "supporting", "detail", "background"}
FONT_ROLES = {"serif", "sans", "script", "display"}
TEXT_FITS = {"none", "shrink_to_fit", "wrap_and_shrink"}
MAX_ELEMENTS = 200
SUPPORTED_ELEMENT_TYPES = {"photo", "text", "rectangle", "ellipse", "line", "polygon", "design_asset"}


def _number(value: Any, name: str, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f"{name} is outside its allowed range")
    return value


def _colour(value: Any, name: str) -> str:
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError(f"{name} must be a #RRGGBB colour")
    return value


def _boolean(value: Any, name: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def validate_page_spec(page: Any) -> dict[str, Any]:
    if not isinstance(page, dict):
        raise ValueError("page_spec must be an object")
    result = dict(page)
    result["type"] = str(result.get("type", "single"))
    if result["type"] not in {"single", "spread"}:
        raise ValueError("page_spec.type must be single or spread")
    for key in ("width_mm", "height_mm"):
        result[key] = _number(result.get(key, 300), key, 20, 2000)
    result["bleed_mm"] = _number(result.get("bleed_mm", 3), "bleed_mm", 0, 100)
    result["safe_margin_mm"] = _number(result.get("safe_margin_mm", 8), "safe_margin_mm", 0, 100)
    result["gutter_mm"] = _number(result.get("gutter_mm", 4), "gutter_mm", 0, 100)
    result["dpi"] = int(_number(result.get("dpi", 300), "dpi", 72, 1200))
    result["background"] = _colour(result.get("background", "#f5f2ed"), "background")
    return result


def _style(element: dict[str, Any]) -> dict[str, Any]:
    border = dict(element.get("border") or {})
    if border:
        border["width_mm"] = _number(border.get("width_mm", 0), "border.width_mm", 0, 30)
        border["color"] = _colour(border.get("color", "#ffffff"), "border.color")
        border["opacity"] = _number(border.get("opacity", 1), "border.opacity", 0, 1)
    shadow = dict(element.get("shadow") or {})
    for key in ("opacity", "blur_mm", "offset_x_mm", "offset_y_mm"):
        if key in shadow:
            shadow[key] = _number(shadow[key], f"shadow.{key}", 0 if key in {"opacity", "blur_mm"} else -100, 1 if key == "opacity" else 100)
    if "color" in shadow:
        shadow["color"] = _colour(shadow["color"], "shadow.color")
    return {"border": border, "shadow": shadow}


def validate_design_spec(payload: Any, asset_ids: set[str], design_asset_ids: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("design spec must be an object")
    if payload.get("format") not in {"PhotoManager Collage Design", "CollageDesignSpec"}:
        raise ValueError("unsupported design spec format")
    schema_version = int(payload.get("schema_version", 0))
    if schema_version not in {1, 2}:
        raise ValueError("unsupported design spec schema_version")
    design_asset_ids = set(design_asset_ids or set())
    page = validate_page_spec(payload.get("page_spec") or {})
    alternatives = payload.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives or len(alternatives) > 5:
        raise ValueError("alternatives must contain between 1 and 5 designs")
    checked = []
    for alternative in alternatives:
        if not isinstance(alternative, dict) or not isinstance(alternative.get("elements"), list):
            raise ValueError("each alternative must contain an elements array")
        if len(alternative["elements"]) < 1 or len(alternative["elements"]) > MAX_ELEMENTS:
            raise ValueError(f"elements must contain between 1 and {MAX_ELEMENTS} items")
        elements = []
        ids: set[str] = set()
        for index, raw in enumerate(alternative["elements"]):
            if not isinstance(raw, dict):
                raise ValueError(f"element {index} must be an object")
            element = deepcopy(raw)
            element_id = str(element.get("id") or "")
            if not element_id or element_id in ids:
                raise ValueError("elements must have unique non-empty ids")
            ids.add(element_id)
            kind = element.get("type")
            if kind not in SUPPORTED_ELEMENT_TYPES:
                raise ValueError(f"unsupported element type: {kind}")
            for key in ("x_mm", "y_mm", "width_mm", "height_mm"):
                element[key] = _number(element.get(key, 0), key, -100 if key[:1] in {"x", "y"} else 0, 3000)
            element["rotation_deg"] = _number(element.get("rotation_deg", 0), "rotation_deg", -3600, 3600)
            element["opacity"] = _number(element.get("opacity", 1), "opacity", 0, 1)
            element["z_index"] = int(_number(element.get("z_index", index), "z_index", -10000, 10000))
            if kind == "photo":
                asset_id = str(element.get("asset_id") or "")
                if asset_id not in asset_ids:
                    raise ValueError(f"photo element references an asset outside the package: {asset_id}")
                element["role"] = str(element.get("role", "detail"))
                if element["role"] not in ROLES:
                    raise ValueError("unsupported photo role")
                image = dict(element.get("image") or {})
                image["rotation_deg"] = _number(image.get("rotation_deg", 0), "image.rotation_deg", -3600, 3600)
                image["focus_x"] = _number(image.get("focus_x", .5), "image.focus_x", 0, 1)
                image["focus_y"] = _number(image.get("focus_y", .5), "image.focus_y", 0, 1)
                image["zoom"] = _number(image.get("zoom", 1), "image.zoom", .5, 10)
                element["image"] = image
                mask = dict(element.get("mask") or {"type": "rectangle"})
                if mask.get("type") not in MASKS:
                    raise ValueError("unsupported photo mask")
                element["mask"] = mask
                element.update(_style(element))
            elif kind == "text":
                if not isinstance(element.get("content"), str) or len(element["content"]) > 2000:
                    raise ValueError("text content is required and must be short")
                text_style = dict(element.get("text_style") or {})
                text_style["font_id"] = str(text_style.get("font_id", "serif"))
                if text_style["font_id"] not in FONT_ROLES:
                    raise ValueError("unsupported font role")
                text_style["font_size_pt"] = _number(text_style.get("font_size_pt", 12), "text_style.font_size_pt", 4, 300)
                text_style["weight"] = str(text_style.get("weight", "normal"))
                if text_style["weight"] not in {"normal", "bold", "600", "700"}:
                    raise ValueError("unsupported text weight")
                text_style["italic"] = bool(text_style.get("italic", False))
                text_style["alignment"] = str(text_style.get("alignment", "left"))
                if text_style["alignment"] not in {"left", "center", "right", "justify"}:
                    raise ValueError("unsupported text alignment")
                text_style["line_height"] = _number(text_style.get("line_height", 1.15), "text_style.line_height", .5, 3)
                text_style["letter_spacing"] = _number(text_style.get("letter_spacing", 0), "text_style.letter_spacing", -20, 100)
                text_style["text_fit"] = str(text_style.get("text_fit", "shrink_to_fit"))
                if text_style["text_fit"] not in TEXT_FITS:
                    raise ValueError("unsupported text_fit")
                if "color" in text_style:
                    text_style["color"] = _colour(text_style["color"], "text_style.color")
                element["text_style"] = text_style
                # Overlapping text and photos can be intentional art direction,
                # but the intent must be explicit. This is separate from
                # allow_bleed, which only controls page-boundary behaviour.
                element["allow_photo_overlap"] = _boolean(element.get("allow_photo_overlap"), "allow_photo_overlap")
                element["allow_text_overlap"] = _boolean(element.get("allow_text_overlap"), "allow_text_overlap")
            elif kind == "design_asset":
                package_asset_id = str(element.get("package_asset_id") or element.get("asset_id") or "")
                if package_asset_id not in design_asset_ids:
                    raise ValueError(f"design asset references an unknown package asset: {package_asset_id}")
                element["package_asset_id"] = package_asset_id
                if "asset_url" in element and not str(element["asset_url"]).startswith("/api/collage/design-assets/"):
                    raise ValueError("design asset URL must be a managed Photo Manager asset URL")
                element["allow_bleed"] = bool(element.get("allow_bleed", False))
            elif kind not in {"line"}:
                fill = element.get("fill")
                if fill is not None:
                    element["fill"] = _colour(fill, "fill")
                if "stroke" in element:
                    element["stroke"] = _colour(element["stroke"], "stroke")
                if "stroke_width" in element:
                    element["stroke_width"] = _number(element["stroke_width"], "stroke_width", 0, 30)
            if kind == "line":
                element["stroke"] = _colour(element.get("stroke", "#292521"), "stroke")
                element["stroke_width"] = _number(element.get("stroke_width", 1), "stroke_width", 0, 30)
            if kind == "polygon":
                points = element.get("points")
                if not isinstance(points, list) or len(points) < 3 or len(points) > 100:
                    raise ValueError("polygon.points must contain between 3 and 100 points")
                checked_points = []
                for point in points:
                    if not isinstance(point, dict):
                        raise ValueError("polygon points must be objects")
                    checked_points.append({
                        "x": _number(point.get("x", 0), "polygon.point.x", -3000, 3000),
                        "y": _number(point.get("y", 0), "polygon.point.y", -3000, 3000),
                    })
                element["points"] = checked_points
            elements.append(element)
        checked.append({**alternative, "elements": sorted(elements, key=lambda x: (x["z_index"], x["id"]))})
    return {**payload, "schema_version": schema_version, "page_spec": page, "alternatives": checked}


def _text_metrics(content: str, style: dict[str, Any], width_mm: float) -> dict[str, float | int]:
    """Deterministic, font-role based text estimate used before publication.

    The editor uses the same role mapping.  This intentionally avoids host font
    names and is conservative for script/display roles so text is repaired
    before it reaches Fabric rather than being silently clipped there.
    """
    font_size = float(style.get("font_size_pt", 12))
    role_factor = {"serif": .52, "sans": .54, "script": .47, "display": .58}.get(str(style.get("font_id", "serif")), .54)
    spacing = float(style.get("letter_spacing", 0)) / 1000 * font_size
    char_mm = max(.6, (font_size * .3528 * role_factor) + spacing)
    line_mm = max(1.0, font_size * .3528 * float(style.get("line_height", 1.15)))
    raw_lines = str(content).splitlines() or [""]
    fit = str(style.get("text_fit", "shrink_to_fit"))
    max_chars = max(1, int(float(width_mm) / char_mm))
    lines = 0
    widest = 0.0
    for raw_line in raw_lines:
        # A shrink-to-fit box must be measured as a single line first; if we
        # wrap it here, the measured width can never exceed the box and the
        # promised font repair would never run.  Explicit wrapping is only
        # part of the wrap_and_shrink policy.
        chunks = ([raw_line] if fit in {"none", "shrink_to_fit"} else
                  [raw_line[index:index + max_chars] for index in range(0, max(1, len(raw_line)), max_chars)]) or [""]
        lines += len(chunks)
        widest = max(widest, max((len(chunk) for chunk in chunks), default=1) * char_mm)
    return {"width_mm": widest, "height_mm": max(line_mm, lines * line_mm), "lines": lines, "char_mm": char_mm}


def _rotated_bounds(element: dict[str, Any]) -> tuple[float, float, float, float]:
    x, y = float(element.get("x_mm", 0)), float(element.get("y_mm", 0))
    width, height = float(element.get("width_mm", 0)), float(element.get("height_mm", 0))
    radians = math.radians(float(element.get("rotation_deg", 0)))
    cos_v, sin_v = abs(math.cos(radians)), abs(math.sin(radians))
    bound_width, bound_height = width * cos_v + height * sin_v, width * sin_v + height * cos_v
    return x + width / 2 - bound_width / 2, y + height / 2 - bound_height / 2, bound_width, bound_height


def validate_and_repair_design_spec(payload: Any, asset_ids: set[str], design_asset_ids: set[str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate a design and apply only bounded, explainable layout repairs."""
    checked = validate_design_spec(payload, asset_ids, design_asset_ids)
    page_width, page_height = page_dimensions_mm(checked["page_spec"])
    safe = float(checked["page_spec"].get("safe_margin_mm", 8))
    warnings: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    for alternative in checked["alternatives"]:
        for element in alternative["elements"]:
            if element["type"] == "text":
                style = element["text_style"]
                fit = style.get("text_fit", "shrink_to_fit")
                metrics = _text_metrics(str(element["content"]), style, float(element["width_mm"]))
                original_size = float(style["font_size_pt"])
                if fit in {"shrink_to_fit", "wrap_and_shrink"} and float(metrics["width_mm"]) > float(element["width_mm"]):
                    while float(metrics["width_mm"]) > float(element["width_mm"]) and float(style["font_size_pt"]) > 6:
                        style["font_size_pt"] = round(float(style["font_size_pt"]) * .94, 2)
                        metrics = _text_metrics(str(element["content"]), style, float(element["width_mm"]))
                    if float(style["font_size_pt"]) != original_size:
                        repairs.append({"element_id": element["id"], "reason": "TEXT_SHRINK_TO_FIT", "from_font_size_pt": original_size, "to_font_size_pt": style["font_size_pt"]})
                if fit == "wrap_and_shrink" and float(metrics["height_mm"]) > float(element["height_mm"]):
                    available = page_height - safe - float(element["y_mm"])
                    if available > float(element["height_mm"]):
                        old_height = float(element["height_mm"])
                        element["height_mm"] = round(min(available, float(metrics["height_mm"])), 2)
                        repairs.append({"element_id": element["id"], "reason": "TEXT_BOX_EXPANDED", "from_height_mm": old_height, "to_height_mm": element["height_mm"]})
                left, top, bound_width, bound_height = _rotated_bounds(element)
                if not element.get("allow_bleed", False):
                    dx = max(safe - left, 0) - max(left + bound_width - (page_width - safe), 0)
                    dy = max(safe - top, 0) - max(top + bound_height - (page_height - safe), 0)
                    if dx or dy:
                        old_x, old_y = float(element["x_mm"]), float(element["y_mm"])
                        element["x_mm"] = round(old_x + dx, 2)
                        element["y_mm"] = round(old_y + dy, 2)
                        new_left, new_top, new_width, new_height = _rotated_bounds(element)
                        if new_left >= safe - .01 and new_top >= safe - .01 and new_left + new_width <= page_width - safe + .01 and new_top + new_height <= page_height - safe + .01:
                            repairs.append({"element_id": element["id"], "reason": "TEXT_SAFE_MARGIN", "dx_mm": round(dx, 2), "dy_mm": round(dy, 2)})
                        else:
                            warnings.append({"element_id": element["id"], "code": "TEXT_OUTSIDE_SAFE_AREA", "message": "Text remains outside the safe margin after bounded repair."})
                final_metrics = _text_metrics(str(element["content"]), style, float(element["width_mm"]))
                if (float(final_metrics["width_mm"]) > float(element["width_mm"]) + .01 or
                        float(final_metrics["height_mm"]) > float(element["height_mm"]) + .01):
                    warnings.append({"element_id": element["id"], "code": "TEXT_OVERFLOW", "message": "Text may overflow its box; edit the text box or font size."})

            left, top, bound_width, bound_height = _rotated_bounds(element)
            if not element.get("allow_bleed", False) and (left < -float(checked["page_spec"].get("bleed_mm", 3)) or top < -float(checked["page_spec"].get("bleed_mm", 3)) or left + bound_width > page_width + float(checked["page_spec"].get("bleed_mm", 3)) or top + bound_height > page_height + float(checked["page_spec"].get("bleed_mm", 3))):
                warnings.append({"element_id": element["id"], "code": "ELEMENT_OUTSIDE_PAGE", "message": "Element extends beyond the allowed bleed."})

        photo_elements = [item for item in alternative["elements"] if item["type"] == "photo"]
        for index, first in enumerate(photo_elements):
            fx, fy, fw, fh = _rotated_bounds(first)
            first_area = max(fw * fh, .001)
            for second in photo_elements[index + 1:]:
                sx, sy, sw, sh = _rotated_bounds(second)
                overlap = max(0.0, min(fx + fw, sx + sw) - max(fx, sx)) * max(0.0, min(fy + fh, sy + sh) - max(fy, sy))
                coverage = overlap / first_area
                if coverage > .20 and str(first.get("role", "detail")) in {"hero", "secondary"}:
                    warnings.append({"element_id": first["id"], "covered_by": second["id"], "code": "EXCESSIVE_PHOTO_OVERLAP", "coverage": round(coverage, 3), "message": "Major photo is covered by another photo; confirm that the overlap is intentional."})
        text_elements = [item for item in alternative["elements"] if item["type"] == "text"]
        for text in text_elements:
            tx, ty, tw, th = _rotated_bounds(text)
            for photo in photo_elements:
                px, py, pw, ph = _rotated_bounds(photo)
                overlap = max(0.0, min(tx + tw, px + pw) - max(tx, px)) * max(0.0, min(ty + th, py + ph) - max(ty, py))
                if overlap / max(tw * th, .001) > .15 and int(photo.get("z_index", 0)) > int(text.get("z_index", 0)):
                    warnings.append({"element_id": text["id"], "covered_by": photo["id"], "code": "TEXT_COVERED_BY_PHOTO", "message": "Text is behind a foreground photo."})

    report = {"validation_status": "repaired" if repairs else ("warnings" if warnings else "valid"), "warnings": warnings, "repairs": repairs}
    return checked, report


def to_collage_document(spec: dict[str, Any], alternative_index: int = 0, asset_map: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    resolved_assets = asset_map or {}
    design_asset_ids = {key for key, value in resolved_assets.items() if isinstance(value, dict) and value.get("package_asset_id")}
    photo_asset_ids = set(resolved_assets) - design_asset_ids
    checked = validate_design_spec(spec, photo_asset_ids, design_asset_ids)
    alternative = checked["alternatives"][alternative_index]
    page = checked["page_spec"]
    width = float(page["width_mm"])
    if page["type"] == "spread":
        width *= 2
    elements = []
    for element in alternative["elements"]:
        item = deepcopy(element)
        item["element_id"] = item.pop("id")
        item["x"] = mm_to_px(item.get("x_mm", 0))
        item["y"] = mm_to_px(item.get("y_mm", 0))
        item["width"] = mm_to_px(item.get("width_mm", 0))
        item["height"] = mm_to_px(item.get("height_mm", 0))
        if item["type"] == "photo":
            item["photo_id"] = item.pop("asset_id")
            item["style"] = {"border": item.pop("border", {}), "shadow": item.pop("shadow", {})}
            item["clipping_shape"] = item.pop("mask", {}).get("type", "rectangle")
            item["transform"] = item.pop("image", {})
            if item.get("template_mask_asset_id"):
                mask_asset_id = str(item["template_mask_asset_id"])
                item["template_mask_url"] = (asset_map or {}).get(mask_asset_id, {}).get("asset_url", item.get("template_mask_url"))
                item["template_mask_asset_id"] = mask_asset_id
            if item.get("slot_id"):
                item["template_slot_id"] = str(item.pop("slot_id"))
        elif item["type"] == "design_asset":
            item["asset_id"] = item.pop("package_asset_id")
            item["asset_url"] = (asset_map or {}).get(item["asset_id"], {}).get("asset_url", item.get("asset_url"))
        elif item["type"] == "polygon":
            item["points"] = [{"x": mm_to_px(point["x"]), "y": mm_to_px(point["y"])} for point in item.get("points", [])]
        if "stroke_width" in item:
            # DesignSpec geometry is physical. Keep the V2 document in the same
            # logical pixels used by every Fabric object, including strokes.
            item["stroke_width"] = mm_to_px(item["stroke_width"])
        elements.append(item)
    layered = checked.get("layered_template")
    if isinstance(layered, dict):
        # Template artwork is part of the same ordered document as photos and
        # text.  This keeps the editor, preview PNG and high-resolution export
        # on one renderer while making foreground/background layers locked by
        # default.  The original manifest remains in metadata for debug tools.
        page_height = mm_to_px(float(page["height_mm"]))
        background_id = layered.get("background_asset_id")
        foreground_id = layered.get("foreground_asset_id")
        template_layers = []
        if background_id:
            template_layers.append({
                "element_id": "template-background",
                "type": "design_asset",
                "asset_id": str(background_id),
                "asset_url": (asset_map or {}).get(str(background_id), {}).get("asset_url", layered.get("background_url")),
                "x": 0, "y": 0, "width": mm_to_px(width), "height": page_height,
                "rotation_deg": 0, "opacity": 1, "z_index": -100000,
                "locked": True, "template_layer": "background", "role": "background",
                "label": "Template background",
            })
        if foreground_id:
            template_layers.append({
                "element_id": "template-foreground",
                "type": "design_asset",
                "asset_id": str(foreground_id),
                "asset_url": (asset_map or {}).get(str(foreground_id), {}).get("asset_url", layered.get("foreground_url")),
                "x": 0, "y": 0, "width": mm_to_px(width), "height": page_height,
                "rotation_deg": 0, "opacity": 1, "z_index": 100000,
                "locked": True, "template_layer": "foreground", "role": "background",
                "label": "Template foreground",
            })
        background_layers = [item for item in template_layers if item.get("template_layer") == "background"]
        foreground_layers = [item for item in template_layers if item.get("template_layer") == "foreground"]
        elements = background_layers + elements + foreground_layers
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    selection_asset_ids = [str(item["asset_id"]) for item in checked.get("assets", [])
                           if isinstance(item, dict) and item.get("asset_id") in photo_asset_ids]
    return {"document_type": "CollageDocument", "schema_version": 2, "document_id": "doc_" + uuid.uuid4().hex, "created_at": now, "modified_at": now,
            "page_spec": page, "canvas": {"width": mm_to_px(width), "height": mm_to_px(float(page["height_mm"])), "gutter": mm_to_px(float(page.get("gutter_mm", 4)))},
            "background": page.get("background", "#f5f2ed"), "elements": elements, "frames": [x for x in elements if x["type"] == "photo"], "cells": [x for x in elements if x["type"] == "photo"],
            "provider": "ai-design", "style": alternative.get("style", ""), "metadata": {
                "design_id": alternative.get("id", ""),
                "design_name": alternative.get("name") or alternative.get("title") or "",
                "design_reason": alternative.get("reason", ""),
                "source": f"CollageDesignSpec v{checked.get('schema_version', 1)}",
                "style_intent": spec.get("style_intent") or alternative.get("style") or spec.get("style") or "",
                "selection_asset_ids": selection_asset_ids,
                **({"layered_template": deepcopy(layered)} if isinstance(layered, dict) else {}),
            }, "edited": True}


def validate_collage_document(payload: Any, asset_ids: set[str], design_asset_ids: set[str] | None = None) -> dict[str, Any]:
    """Validate the V2 document written by the editor before publishing it."""
    if not isinstance(payload, dict) or payload.get("document_type") != "CollageDocument":
        raise ValueError("payload must be a CollageDocument")
    if int(payload.get("schema_version", 0)) != 2:
        raise ValueError("unsupported CollageDocument schema_version")
    page = validate_page_spec(payload.get("page_spec") or {})
    elements = payload.get("elements")
    if not isinstance(elements, list) or not 1 <= len(elements) <= MAX_ELEMENTS:
        raise ValueError(f"elements must contain between 1 and {MAX_ELEMENTS} items")
    checked = []
    seen: set[str] = set()
    for index, raw in enumerate(elements):
        if not isinstance(raw, dict):
            raise ValueError(f"element {index} must be an object")
        item = deepcopy(raw)
        element_id = str(item.get("element_id") or item.get("id") or "")
        if not element_id or element_id in seen:
            raise ValueError("elements must have unique non-empty element_id values")
        seen.add(element_id)
        kind = item.get("type")
        if kind not in SUPPORTED_ELEMENT_TYPES:
            raise ValueError(f"unsupported element type: {kind}")
        for key in ("x", "y", "width", "height"):
            item[key] = _number(item.get(key, 0), key, -400, 12000 if key in {"x", "y"} else 12000)
        if kind == "photo":
            photo_id = str(item.get("photo_id") or "")
            if photo_id not in asset_ids:
                raise ValueError(f"document references an unknown asset: {photo_id}")
        if kind == "design_asset":
            package_asset_id = str(item.get("asset_id") or item.get("package_asset_id") or "")
            if package_asset_id not in set(design_asset_ids or set()):
                raise ValueError(f"document references an unknown design asset: {package_asset_id}")
        if kind == "text" and (not isinstance(item.get("content"), str) or len(item["content"]) > 2000):
            raise ValueError("text content is required and must be short")
        if kind == "text":
            item["allow_photo_overlap"] = _boolean(item.get("allow_photo_overlap"), "allow_photo_overlap")
            item["allow_text_overlap"] = _boolean(item.get("allow_text_overlap"), "allow_text_overlap")
        checked.append(item)
    return {**payload, "page_spec": page, "elements": checked}
