"""Pair JPEG/RAW files and consolidate them into capture-date folders.

This module deliberately operates on filesystem paths, not catalog rows.  It is
safe to preview first and is idempotent: files already at their planned
destination are skipped, while ambiguous or conflicting destinations abort a
move before any file is changed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from photovault.catalog.metadata import extract_metadata

JPEG_SUFFIXES = frozenset({".jpg", ".jpeg"})
RAW_SUFFIXES = frozenset({".nef", ".nrw", ".cr2", ".cr3", ".arw", ".dng", ".raf", ".orf", ".rw2"})
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"})
MEDIA_SUFFIXES = JPEG_SUFFIXES | RAW_SUFFIXES | VIDEO_SUFFIXES


@dataclass(frozen=True)
class ConsolidationPair:
    key: str
    jpeg: Path | None
    raw: Path | None
    videos: tuple[Path, ...]
    capture_date: str | None
    date_source: str
    warning: str | None = None


@dataclass(frozen=True)
class ConsolidationAction:
    source: Path
    destination: Path
    pair_key: str
    status: str  # MOVE, ALREADY_PRESENT, CONFLICT
    reason: str


@dataclass(frozen=True)
class ConsolidationPlan:
    source_folders: tuple[Path, ...]
    destination: Path
    pairs: tuple[ConsolidationPair, ...]
    actions: tuple[ConsolidationAction, ...]
    unpaired_jpegs: tuple[Path, ...]
    unpaired_raw: tuple[Path, ...]
    warnings: tuple[str, ...]

    @property
    def conflicts(self) -> tuple[ConsolidationAction, ...]:
        return tuple(action for action in self.actions if action.status == "CONFLICT")

    @property
    def moves(self) -> tuple[ConsolidationAction, ...]:
        return tuple(action for action in self.actions if action.status == "MOVE")

    @property
    def already_present(self) -> tuple[ConsolidationAction, ...]:
        return tuple(action for action in self.actions if action.status == "ALREADY_PRESENT")

    @property
    def videos(self) -> tuple[Path, ...]:
        return tuple(action.source for action in self.actions if action.source.suffix.lower() in VIDEO_SUFFIXES)


def _media_files(folders: Iterable[Path]) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for folder in folders:
        root = folder.expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"source folder is not available: {root}")
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES:
                result.setdefault(path.stem.casefold(), []).append(path)
    return result


def _capture_date(path: Path) -> tuple[str | None, str]:
    record = extract_metadata(path)
    if record.capture_datetime:
        return record.capture_datetime[:10], record.date_source or "embedded_metadata"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d"), "filesystem_modified"


def _choose_date(jpeg: Path | None, raw: Path | None, videos: Iterable[Path] = ()) -> tuple[str | None, str, str | None]:
    jpeg_date = _capture_date(jpeg) if jpeg else (None, "")
    raw_date = _capture_date(raw) if raw else (None, "")
    if jpeg_date[0] and raw_date[0] and jpeg_date[0] != raw_date[0]:
        return jpeg_date[0], jpeg_date[1], f"JPEG/RAW capture dates differ: {jpeg_date[0]} vs {raw_date[0]}"
    if jpeg_date[0]:
        return jpeg_date[0], jpeg_date[1], None
    if raw_date[0]:
        return raw_date[0], raw_date[1], None
    for video in videos:
        video_date = _capture_date(video)
        if video_date[0]:
            return video_date[0], video_date[1], None
    return None, "", None


def build_consolidation_plan(source_folders: Iterable[Path], destination: Path) -> ConsolidationPlan:
    folders = tuple(folder.expanduser().resolve() for folder in source_folders)
    destination = destination.expanduser().resolve()
    if not folders:
        raise ValueError("at least one source folder is required")
    if destination in folders or any(folder in destination.parents for folder in folders):
        raise ValueError("destination cannot be inside a source folder")

    by_stem = _media_files(folders)
    pairs: list[ConsolidationPair] = []
    actions: list[ConsolidationAction] = []
    unpaired_jpegs: list[Path] = []
    unpaired_raw: list[Path] = []
    warnings: list[str] = []
    for key in sorted(by_stem):
        files = by_stem[key]
        jpegs = [path for path in files if path.suffix.lower() in JPEG_SUFFIXES]
        raws = [path for path in files if path.suffix.lower() in RAW_SUFFIXES]
        videos = sorted(path for path in files if path.suffix.lower() in VIDEO_SUFFIXES)
        if len(jpegs) > 1 or len(raws) > 1:
            warnings.append(f"duplicate stem {key}: {len(jpegs)} JPEG, {len(raws)} RAW")
        jpeg = sorted(jpegs)[0] if jpegs else None
        raw = sorted(raws)[0] if raws else None
        if jpeg is None:
            unpaired_raw.extend(raws)
        if raw is None:
            unpaired_jpegs.extend(jpegs)
        capture_date, date_source, warning = _choose_date(jpeg, raw, videos)
        if warning:
            warnings.append(f"{key}: {warning}")
        pair = ConsolidationPair(key, jpeg, raw, tuple(videos), capture_date, date_source, warning)
        pairs.append(pair)
        if not capture_date:
            warnings.append(f"{key}: no usable capture date")
            continue
        for path in (jpeg, raw, *videos):
            if path is None:
                continue
            target = destination / capture_date / path.name
            if target == path:
                status, reason = "ALREADY_PRESENT", "file is already in the target date folder"
            elif target.exists():
                same = target.is_file() and target.stat().st_size == path.stat().st_size
                status = "ALREADY_PRESENT" if same else "CONFLICT"
                reason = "same-size destination already exists" if same else "destination exists with different size"
            else:
                status, reason = "MOVE", "same-filesystem rename/move; file bytes are untouched"
            actions.append(ConsolidationAction(path, target, key, status, reason))
    return ConsolidationPlan(folders, destination, tuple(pairs), tuple(actions), tuple(sorted(unpaired_jpegs)), tuple(sorted(unpaired_raw)), tuple(warnings))


def execute_consolidation(plan: ConsolidationPlan, progress: Callable[[ConsolidationAction], None] | None = None) -> dict[str, int]:
    """Move a conflict-free plan and return counts.  No overwrite is allowed."""
    if plan.conflicts:
        raise ValueError(f"consolidation has {len(plan.conflicts)} destination conflict(s); nothing was moved")
    moved = skipped = 0
    for action in plan.actions:
        if action.status == "ALREADY_PRESENT":
            skipped += 1
            if progress:
                progress(action)
            continue
        action.destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(action.source, action.destination)
        moved += 1
        if progress:
            progress(action)
    return {"moved": moved, "skipped": skipped, "pairs": len(plan.pairs), "unpaired_jpegs": len(plan.unpaired_jpegs), "unpaired_raw": len(plan.unpaired_raw)}


def render_consolidation_report(plan: ConsolidationPlan, result: dict[str, int] | None = None) -> str:
    """Render a human-readable audit report suitable for the UI or a text file."""
    result = result or {}
    lines = [
        "Photo Manager — JPEG/RAW Consolidation Report",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Destination: {plan.destination}",
        "Source folders:",
        *(f"  - {folder}" for folder in plan.source_folders),
        "",
        "Summary:",
        f"  JPEG/RAW stems checked: {len(plan.pairs)}",
        f"  Files moved: {result.get('moved', len(plan.moves))}",
        f"  Files already present/skipped: {result.get('skipped', len(plan.already_present))}",
        f"  JPEG without matching RAW: {len(plan.unpaired_jpegs)}",
        f"  RAW without matching JPEG: {len(plan.unpaired_raw)}",
        f"  Videos consolidated by capture date: {len(plan.videos)}",
        f"  Destination conflicts: {len(plan.conflicts)}",
        "",
        "JPEG without matching RAW:",
    ]
    lines.extend(f"  - {path}" for path in plan.unpaired_jpegs)
    lines.append("\nRAW without matching JPEG:")
    lines.extend(f"  - {path}" for path in plan.unpaired_raw)
    if plan.warnings:
        lines.append("\nWarnings:")
        lines.extend(f"  - {warning}" for warning in plan.warnings)
    return "\n".join(lines) + "\n"


def write_consolidation_report(plan: ConsolidationPlan, output: Path, result: dict[str, int] | None = None) -> Path:
    """Write a consolidation report, creating only the requested report file."""
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_consolidation_report(plan, result), encoding="utf-8")
    return output
