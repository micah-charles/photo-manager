"""Explicit, local-only wrapper for the macOS Vision geometry POC."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


MAX_IMAGES_PER_BATCH = 200
_HELPER = Path(__file__).parent / "platform" / "macos" / "local_vision_analyzer.swift"


class VisionPocError(RuntimeError):
    """The opt-in native Vision POC could not run or returned invalid data."""


def _validate_box(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        raise VisionPocError("Vision returned a malformed bounding box")
    box: dict[str, float] = {}
    for key in ("left", "top", "right", "bottom"):
        coordinate = value.get(key)
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)) or not math.isfinite(coordinate):
            raise VisionPocError("Vision returned a non-finite bounding-box coordinate")
        if not 0 <= coordinate <= 1:
            raise VisionPocError("Vision returned a coordinate outside the normalized image bounds")
        box[key] = float(coordinate)
    if box["left"] >= box["right"] or box["top"] >= box["bottom"]:
        raise VisionPocError("Vision returned an empty bounding box")
    return box


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("engine") != "apple-vision":
        raise VisionPocError("Unsupported local Vision result format")
    if payload.get("coordinate_space") is not None:
        raise VisionPocError("Coordinate space belongs to each image result, not the batch")
    if not isinstance(payload.get("images"), list) or not isinstance(payload.get("errors"), list):
        raise VisionPocError("Local Vision result must contain image and error lists")
    for error in payload["errors"]:
        if not isinstance(error, dict) or not isinstance(error.get("source"), str) or not isinstance(error.get("message"), str):
            raise VisionPocError("Vision returned a malformed per-image error")
    for image in payload["images"]:
        if not isinstance(image, dict) or image.get("coordinate_space") != "oriented" or image.get("box_convention") != "normalized-top-left":
            raise VisionPocError("Vision result has an unsupported coordinate convention")
        if not isinstance(image.get("source"), str) or not isinstance(image.get("filename"), str):
            raise VisionPocError("Vision result is missing its source identity")
        for dimension in (image.get("width"), image.get("height")):
            if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
                raise VisionPocError("Vision result has invalid oriented pixel dimensions")
        orientation = image.get("exif_orientation")
        if isinstance(orientation, bool) or not isinstance(orientation, int) or not 1 <= orientation <= 8:
            raise VisionPocError("Vision result has invalid EXIF orientation metadata")
        elapsed = image.get("elapsed_ms")
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
            raise VisionPocError("Vision result has invalid timing metadata")
        if not isinstance(image.get("faces"), list) or not isinstance(image.get("subjects"), list):
            raise VisionPocError("Vision result is missing face or person observations")
        for face in image["faces"]:
            if not isinstance(face, dict):
                raise VisionPocError("Vision returned a malformed face observation")
            _validate_box(face.get("box"))
            confidence = face.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise VisionPocError("Vision returned an invalid face confidence")
        for subject in image["subjects"]:
            if not isinstance(subject, dict):
                raise VisionPocError("Vision returned a malformed person observation")
            if subject.get("label") != "person":
                raise VisionPocError("Vision returned an unsupported subject label")
            _validate_box(subject.get("box"))
            confidence = subject.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise VisionPocError("Vision returned an invalid person confidence")
    return payload


def template_analysis(image_result: dict[str, Any]) -> dict[str, Any]:
    """Adapt one validated observation to the existing template-engine input."""
    if not isinstance(image_result, dict):
        raise VisionPocError("Cannot adapt a malformed Vision image result")
    try:
        validate_payload({"schema_version": 1, "engine": "apple-vision", "images": [image_result], "errors": []})
    except VisionPocError as exc:
        if "coordinate convention" in str(exc):
            raise VisionPocError("Cannot adapt an unknown Vision coordinate convention") from exc
        raise
    return {
        "coordinate_space": "oriented",
        "faces": [
            {**_validate_box(face.get("box")), "confidence": float(face["confidence"])}
            for face in image_result.get("faces", [])
        ],
        "subjects": [
            {"label": "person", "box": _validate_box(subject.get("box")), "confidence": float(subject["confidence"])}
            for subject in image_result.get("subjects", [])
        ],
    }


def analyze_images(paths: list[Path], *, timeout_seconds: int = 600) -> dict[str, Any]:
    """Analyze only explicitly supplied still images; do not modify catalog or media."""
    if sys.platform != "darwin":
        raise VisionPocError("The Apple Vision POC runs on macOS only")
    if not paths:
        raise VisionPocError("Supply at least one local image path")
    if len(paths) > MAX_IMAGES_PER_BATCH:
        raise VisionPocError(f"POC batches are limited to {MAX_IMAGES_PER_BATCH} images")
    inputs = [Path(path).expanduser().resolve() for path in paths]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise VisionPocError("Image path does not exist or is not a file: " + ", ".join(missing[:5]))
    if not _HELPER.is_file():
        raise VisionPocError(f"The local Vision helper is missing: {_HELPER}")
    swift = shutil.which("swift")
    if not swift:
        raise VisionPocError("Swift is unavailable; install/select Xcode command-line tools")

    try:
        completed = subprocess.run(
            [swift, str(_HELPER), *(str(path) for path in inputs)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise VisionPocError(f"Vision analysis exceeded the {timeout_seconds}-second batch limit") from exc
    except OSError as exc:
        raise VisionPocError(f"Could not start the Swift Vision helper: {exc}") from exc

    try:
        payload = validate_payload(json.loads(completed.stdout))
    except (json.JSONDecodeError, VisionPocError) as exc:
        detail = completed.stderr.strip() or str(exc)
        raise VisionPocError(f"The Vision helper returned an invalid response: {detail}") from exc
    if completed.returncode not in (0, 1):
        raise VisionPocError(completed.stderr.strip() or f"Vision helper exited with status {completed.returncode}")
    return payload
