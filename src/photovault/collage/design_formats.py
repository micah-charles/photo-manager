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

HEX = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
MASKS = {"rectangle", "rounded", "circle", "ellipse"}
ROLES = {"hero", "secondary", "supporting", "detail", "background"}
MAX_ELEMENTS = 200


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


def validate_design_spec(payload: Any, asset_ids: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("design spec must be an object")
    if payload.get("format") not in {"PhotoManager Collage Design", "CollageDesignSpec"}:
        raise ValueError("unsupported design spec format")
    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("unsupported design spec schema_version")
    page = validate_page_spec(payload.get("page_spec") or {})
    alternatives = payload.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives or len(alternatives) > 5:
        raise ValueError("alternatives must contain between 1 and 5 designs")
    checked = []
    for alternative in alternatives:
        if not isinstance(alternative, dict) or not isinstance(alternative.get("elements"), list):
            raise ValueError("each alternative must contain an elements array")
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
            if kind not in {"photo", "text", "rectangle", "ellipse", "line", "polygon", "paper_shape", "brush_shape"}:
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
                text_style["font_size_pt"] = _number(text_style.get("font_size_pt", 12), "text_style.font_size_pt", 4, 300)
                if "color" in text_style:
                    text_style["color"] = _colour(text_style["color"], "text_style.color")
                element["text_style"] = text_style
            elif kind not in {"line"}:
                fill = element.get("fill")
                if fill is not None:
                    element["fill"] = _colour(fill, "fill")
                if "stroke" in element:
                    element["stroke"] = _colour(element["stroke"], "stroke")
            elements.append(element)
        checked.append({**alternative, "elements": sorted(elements, key=lambda x: (x["z_index"], x["id"]))})
    return {**payload, "page_spec": page, "alternatives": checked}


def to_collage_document(spec: dict[str, Any], alternative_index: int = 0, asset_map: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    checked = validate_design_spec(spec, set((asset_map or {}).keys()))
    alternative = checked["alternatives"][alternative_index]
    page = checked["page_spec"]
    width = float(page["width_mm"])
    if page["type"] == "spread":
        width *= 2
    scale = 4
    elements = []
    for element in alternative["elements"]:
        item = deepcopy(element)
        item["element_id"] = item.pop("id")
        item["x"] = round(float(item.get("x_mm", 0)) * scale)
        item["y"] = round(float(item.get("y_mm", 0)) * scale)
        item["width"] = round(float(item.get("width_mm", 0)) * scale)
        item["height"] = round(float(item.get("height_mm", 0)) * scale)
        if item["type"] == "photo":
            item["photo_id"] = item.pop("asset_id")
            item["style"] = {**item.pop("border", {}), **item.pop("shadow", {})}
            item["clipping_shape"] = item.pop("mask", {}).get("type", "rectangle")
            item["transform"] = item.pop("image", {})
        elements.append(item)
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    return {"document_type": "CollageDocument", "schema_version": 2, "document_id": "doc_" + uuid.uuid4().hex, "created_at": now, "modified_at": now,
            "page_spec": page, "canvas": {"width": round(width * scale), "height": round(float(page["height_mm"]) * scale), "gutter": round(float(page.get("gutter_mm", 4)) * scale)},
            "background": page.get("background", "#f5f2ed"), "elements": elements, "frames": [x for x in elements if x["type"] == "photo"], "cells": [x for x in elements if x["type"] == "photo"],
            "provider": "ai-design", "style": alternative.get("style", ""), "metadata": {"design_reason": alternative.get("reason", ""), "source": "CollageDesignSpec v1"}, "edited": True}
