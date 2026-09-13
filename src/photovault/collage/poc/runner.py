from __future__ import annotations

import time
import uuid
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..analysis import discover_photos
from ..crop import optimise_cell
from ..models import Canvas, PageSpec, page_spec_from_dict
from ..providers import BSPProvider, CeweLayoutProvider, NativeProvider
from ..render import render_candidate, write_contact_sheet, write_crop_comparison_sheet, write_metadata

PROVIDER_TYPES = {
    "native": NativeProvider,
    "cewe-genetic": CeweLayoutProvider,
    "bsp": BSPProvider,
}


def run_poc(folder: Path, output: Path, limit: int = 15, seed: int = 42,
            providers: list[str] | None = None, count: int = 10,
            source_run_id: str = "") -> dict[str, object]:
    started = time.perf_counter()
    photos = discover_photos(folder.expanduser().resolve(), limit)
    return run_poc_photos(photos, output, seed=seed, started=started, providers=providers, count=count, source_run_id=source_run_id)


def run_poc_photos(photos, output: Path, seed: int = 42, started: float | None = None,
                   providers: list[str] | None = None, count: int = 10,
                   source_run_id: str = "", page_spec: PageSpec | dict[str, object] | None = None,
                   photo_transforms: dict[str, dict[str, object]] | None = None,
                   progress_callback: Callable[[int, str], None] | None = None) -> dict[str, object]:
    started = started or time.perf_counter()
    if not 1 <= len(photos) <= 20:
        raise ValueError(f"POC expects 1–20 readable images, found {len(photos)}")
    page_spec = page_spec_from_dict(page_spec) if isinstance(page_spec, dict) else (page_spec or PageSpec())
    canvas = page_spec.to_preview_canvas()
    selected_providers = providers or list(PROVIDER_TYPES)
    if not selected_providers or any(name not in PROVIDER_TYPES for name in selected_providers):
        raise ValueError("choose one or more valid layout providers")
    if not 1 <= count <= 30:
        raise ValueError("candidate count per provider must be between 1 and 30")
    candidates = []
    run_id = source_run_id or uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    provider_timings = {}
    for provider_name in selected_providers:
        provider = PROVIDER_TYPES[provider_name]()
        provider_started = time.perf_counter()
        generated = provider.generate(photos, canvas, seed, count)
        for candidate in generated:
            candidate.page_spec = page_spec.to_dict()
            candidate.document_id = f"doc_{uuid.uuid4().hex}"
            candidate.source_run_id = run_id
            candidate.created_at = now
            candidate.modified_at = now
            candidate.cells = [optimise_cell(cell, {photo.photo_id: photo for photo in photos}[cell.photo_id]) for cell in candidate.cells]
            if photo_transforms:
                candidate.cells = [replace(cell, transform={**cell.transform, **photo_transforms.get(cell.photo_id, {})}) for cell in candidate.cells]
            reasons = {cell.crop_metadata["hard_rejection_reason"] for cell in candidate.cells if cell.crop_metadata.get("hard_rejection_reason")}
            if any(cell.x < 0 or cell.y < 0 or cell.x + cell.width > canvas.width or cell.y + cell.height > canvas.height or cell.width <= 0 or cell.height <= 0 for cell in candidate.cells):
                reasons.add("INVALID_GEOMETRY")
            candidate.rejection_reasons = sorted(reasons)
            candidate.rejected = bool(candidate.rejection_reasons)
        candidates.extend(generated)
        provider_timings[provider.name] = round(time.perf_counter() - provider_started, 3)
        if progress_callback:
            progress_callback(45 + int((len(candidates) / (len(selected_providers) * count)) * 15), f"generated {len(candidates)}/{len(selected_providers) * count} candidates")
    previews = []
    photo_map = {photo.photo_id: photo for photo in photos}
    for index, candidate in enumerate(candidates):
        if progress_callback:
            progress_callback(60 + int(index / max(1, len(candidates)) * 25), f"rendering candidate {index + 1}/{len(candidates)}")
        path = output / "previews" / f"{candidate.provider}-{candidate.candidate_number:02d}-seed-{candidate.seed}.jpg"
        render_candidate(candidate, photo_map, path)
        previews.append((candidate, path))
    if progress_callback:
        progress_callback(88, "building contact sheets")
    write_contact_sheet(previews, output / "contact-sheet.jpg")
    write_crop_comparison_sheet(candidates, photo_map, output / "crop-comparison.jpg")
    write_metadata(candidates, output / "candidates.json")
    documents = output / "documents"
    for candidate in candidates:
        document_path = documents / f"{candidate.document_id}.json"
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(json.dumps(candidate.to_document(), indent=2, default=str), encoding="utf-8")
    write_metadata([candidate for candidate in candidates if candidate.rejected], output / "rejected.json")
    analysis_ms = round(sum((getattr(photo.analysis, "detection_ms", 0.0) for photo in photos)), 3)
    changed = sum(1 for candidate in candidates for cell in candidate.cells if cell.crop_metadata.get("smart_crop_changed"))
    avoided = sum(1 for candidate in candidates for cell in candidate.cells if cell.crop_metadata.get("smart_crop_changed") and not cell.crop_metadata.get("hard_rejection_reason"))
    return {"photo_count": len(photos), "candidate_count": len(candidates), "surviving_candidates": sum(not candidate.rejected for candidate in candidates), "rejected_candidates": sum(candidate.rejected for candidate in candidates), "analysis_ms": analysis_ms, "smart_crop_changed_cells": changed, "face_cut_problems_avoided": avoided, "output": str(output), "provider_seconds": provider_timings, "elapsed_seconds": round(time.perf_counter() - started, 3)}
