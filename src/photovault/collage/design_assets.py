"""Safe handling for decorative assets supplied in AI design packages.

This module intentionally uses only the Python standard library for ZIP and SVG
handling.  SVG is parsed and rewritten through an allow-list before it can be
served to the browser; it is never rendered from untrusted markup directly.
"""
from __future__ import annotations

import hashlib
import io
import math
import posixpath
import re
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from typing import Any
import zipfile

ALLOWED_MEDIA = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp"}
MAX_PACKAGE_BYTES = 25 * 1024 * 1024
MAX_PACKAGE_FILES = 80
MAX_DECORATIVE_ASSET_BYTES = 8 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 20 * 1024 * 1024
PACKAGE_ID_RE = re.compile(r"^pkg_[0-9a-f]{32}$")
ASSET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

_SVG_TAGS = {
    "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline",
    "polygon", "defs", "linearGradient", "radialGradient", "stop", "clipPath",
}
_SVG_ATTRS = {
    "id", "viewBox", "width", "height", "preserveAspectRatio", "d", "x", "y",
    "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry", "points", "fill",
    "fill-opacity", "stroke", "stroke-width", "stroke-opacity", "opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "fill-rule", "clip-rule",
    "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
    "transform", "clip-path", "clipPathUnits", "xmlns",
}
_HEX_OR_FUNCTION = re.compile(r"^(?:none|currentColor|#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgba?\([^)]{1,80}\))$")
_SVG_ENUM_ATTRS = {
    "stroke-linecap": {"butt", "round", "square", "inherit"},
    "stroke-linejoin": {"arcs", "bevel", "miter", "miter-clip", "round", "inherit"},
    "fill-rule": {"nonzero", "evenodd", "inherit"},
    "clip-rule": {"nonzero", "evenodd", "inherit"},
}
_SVG_LENGTH_RE = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))(px|pt|mm|cm|in)?$")
_SVG_VIEWBOX_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))[\s,]+([+-]?(?:\d+(?:\.\d*)?|\.\d+))[\s,]+([+-]?(?:\d+(?:\.\d*)?|\.\d+))[\s,]+([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_member_name(name: str) -> str:
    """Return a normalized ZIP member path or raise on traversal."""
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError("package contains an invalid asset path")
    if "\\" in name:
        raise ValueError("package paths must use forward slashes")
    normalized = posixpath.normpath(name)
    if normalized.startswith("/") or normalized == "." or normalized.startswith("../") or "/../" in normalized:
        raise ValueError("package asset path escapes the package")
    if normalized != name:
        raise ValueError("package contains a non-canonical asset path")
    if str(PurePosixPath(normalized)) != normalized:
        raise ValueError("package contains an invalid asset path")
    return normalized


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _svg_length(value: object) -> float | None:
    """Convert a numeric SVG length to user units, or return None for percentages."""
    match = _SVG_LENGTH_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or ""
    factor = {"": 1.0, "px": 1.0, "pt": 96 / 72, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96}.get(unit)
    return number * factor if factor is not None else None


def _svg_viewbox(value: object) -> tuple[float, float, float, float] | None:
    match = _SVG_VIEWBOX_RE.fullmatch(str(value or ""))
    if not match:
        return None
    left, top, width, height = (float(match.group(index)) for index in range(1, 5))
    if width <= 0 or height <= 0 or not all(math.isfinite(item) for item in (left, top, width, height)):
        return None
    return left, top, width, height


def _svg_number(value: object) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _svg_visible_bounds(root: ET.Element) -> tuple[float, float, float, float] | None:
    """Find conservative bounds for primitive artwork that has numeric geometry.

    Paths and transformed groups are deliberately left to the browser parser; the
    normalizer still makes their viewBox explicit, while these simple primitives
    can safely expand a too-tight viewBox without interpreting arbitrary SVG code.
    """
    bounds: list[tuple[float, float, float, float]] = []
    for node in root.iter():
        tag = _local_name(node.tag)
        attrs = {key.rsplit("}", 1)[-1]: value for key, value in node.attrib.items()}
        values = {key: _svg_number(attrs.get(key)) for key in ("x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry")}
        if tag == "rect" and values["x"] is not None and values["y"] is not None:
            width, height = _svg_number(attrs.get("width")), _svg_number(attrs.get("height"))
            if width is not None and height is not None:
                bounds.append((values["x"], values["y"], values["x"] + width, values["y"] + height))
        elif tag == "circle" and all(values[key] is not None for key in ("cx", "cy", "r")):
            bounds.append((values["cx"] - values["r"], values["cy"] - values["r"], values["cx"] + values["r"], values["cy"] + values["r"]))
        elif tag == "ellipse" and all(values[key] is not None for key in ("cx", "cy", "rx", "ry")):
            bounds.append((values["cx"] - values["rx"], values["cy"] - values["ry"], values["cx"] + values["rx"], values["cy"] + values["ry"]))
        elif tag == "line" and all(values[key] is not None for key in ("x1", "y1", "x2", "y2")):
            bounds.append((min(values["x1"], values["x2"]), min(values["y1"], values["y2"]), max(values["x1"], values["x2"]), max(values["y1"], values["y2"])))
        elif tag in {"polygon", "polyline"}:
            raw_points = re.findall(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", str(attrs.get("points") or ""))
            numbers = [float(value) for value in raw_points]
            if len(numbers) >= 4 and len(numbers) % 2 == 0:
                xs, ys = numbers[0::2], numbers[1::2]
                bounds.append((min(xs), min(ys), max(xs), max(ys)))
    if not bounds:
        return None
    return min(item[0] for item in bounds), min(item[1] for item in bounds), max(item[2] for item in bounds), max(item[3] for item in bounds)


def _normalize_svg_root(root: ET.Element) -> None:
    """Give every accepted SVG deterministic dimensions and a meet viewBox."""
    viewbox = _svg_viewbox(root.attrib.get("viewBox"))
    width = _svg_length(root.attrib.get("width"))
    height = _svg_length(root.attrib.get("height"))
    if viewbox is None:
        if width is None or height is None or width <= 0 or height <= 0:
            raise ValueError("SVG requires positive width/height or a valid viewBox")
        viewbox = (0.0, 0.0, width, height)
    left, top, view_width, view_height = viewbox
    width = width if width is not None and width > 0 else view_width
    height = height if height is not None and height > 0 else view_height
    visible = _svg_visible_bounds(root)
    if visible:
        min_x, min_y, max_x, max_y = visible
        original_right = left + view_width
        original_bottom = top + view_height
        # Include a conservative stroke allowance when primitive artwork reaches
        # the edge. This prevents browser/Fabric parsing from visibly cropping it.
        stroke = max((_svg_number(node.attrib.get("stroke-width")) or 0 for node in root.iter()), default=0) / 2
        left = min(left, min_x - stroke)
        top = min(top, min_y - stroke)
        right = max(original_right, max_x + stroke)
        bottom = max(original_bottom, max_y + stroke)
        view_width, view_height = right - left, bottom - top
    root.set("width", f"{width:g}")
    root.set("height", f"{height:g}")
    root.set("viewBox", f"{left:g} {top:g} {view_width:g} {view_height:g}")
    # Imported artwork must never be stretched by a renderer-specific default.
    root.set("preserveAspectRatio", "xMidYMid meet")


def sanitize_svg(raw: bytes) -> bytes:
    """Sanitize a small decorative SVG using a strict element/attribute allow-list."""
    if len(raw) > MAX_DECORATIVE_ASSET_BYTES:
        raise ValueError("SVG asset is too large")
    lowered = raw.lower()
    if any(token in lowered for token in (b"<!doctype", b"<!entity", b"<script", b"foreignobject", b"javascript:", b"data:", b"xlink:href", b"href=")):
        raise ValueError("SVG contains unsafe executable or external content")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("SVG is not well formed") from exc
    if _local_name(root.tag) != "svg":
        raise ValueError("SVG root must be svg")

    def visit(node: ET.Element) -> None:
        tag = _local_name(node.tag)
        if tag not in _SVG_TAGS:
            raise ValueError(f"SVG element is not allowed: {tag}")
        cleaned: dict[str, str] = {}
        for raw_name, value in node.attrib.items():
            name = raw_name.rsplit("}", 1)[-1]
            if name.lower().startswith("on") or name not in _SVG_ATTRS:
                raise ValueError(f"SVG attribute is not allowed: {name}")
            value = str(value).strip()
            if name == "xmlns" and value == "http://www.w3.org/2000/svg":
                cleaned[name] = value
                continue
            if any(token in value.lower() for token in ("javascript:", "data:", "http:", "https:", "url(", "<", ">")):
                raise ValueError("SVG contains an unsafe external reference")
            if name in {"fill", "stroke", "stop-color"} and not _HEX_OR_FUNCTION.fullmatch(value):
                raise ValueError("SVG contains an unsafe colour value")
            if name in _SVG_ENUM_ATTRS and value not in _SVG_ENUM_ATTRS[name]:
                raise ValueError(f"SVG contains an invalid {name} value")
            cleaned[name] = value
        node.attrib.clear()
        node.attrib.update(cleaned)
        if node.text and node.text.strip() and tag not in {"svg", "g"}:
            raise ValueError("SVG text nodes are not allowed")
        for child in list(node):
            visit(child)

    visit(root)
    _normalize_svg_root(root)
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def validate_zip_members(archive: zipfile.ZipFile, package_size: int) -> list[str]:
    if package_size > MAX_PACKAGE_BYTES:
        raise ValueError("design package is too large")
    infos = archive.infolist()
    if len(infos) > MAX_PACKAGE_FILES:
        raise ValueError("design package contains too many files")
    names: list[str] = []
    total = 0
    for info in infos:
        name = safe_member_name(info.filename)
        if info.is_dir():
            continue
        if name in names:
            raise ValueError("design package contains duplicate paths")
        names.append(name)
        total += int(info.file_size)
        if total > MAX_TOTAL_ASSET_BYTES:
            raise ValueError("design package assets are too large")
    return names


def read_asset_bytes(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        raw = archive.read(name)
    except KeyError as exc:
        raise ValueError(f"package asset is missing: {name}") from exc
    if len(raw) > MAX_DECORATIVE_ASSET_BYTES:
        raise ValueError("decorative asset is too large")
    return raw
