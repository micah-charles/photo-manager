"""Safe handling for decorative assets supplied in AI design packages.

This module intentionally uses only the Python standard library for ZIP and SVG
handling.  SVG is parsed and rewritten through an allow-list before it can be
served to the browser; it is never rendered from untrusted markup directly.
"""
from __future__ import annotations

import hashlib
import io
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
    "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
    "transform", "clip-path", "clipPathUnits", "xmlns",
}
_HEX_OR_FUNCTION = re.compile(r"^(?:none|currentColor|#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgba?\([^)]{1,80}\))$")


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
            cleaned[name] = value
        node.attrib.clear()
        node.attrib.update(cleaned)
        if node.text and node.text.strip() and tag not in {"svg", "g"}:
            raise ValueError("SVG text nodes are not allowed")
        for child in list(node):
            visit(child)

    visit(root)
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
