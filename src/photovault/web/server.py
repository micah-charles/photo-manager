"""Small dependency-free local web server for the PhotoVault Library UI."""
from __future__ import annotations

import json
import mimetypes
import base64
import io
import zipfile
import threading
import uuid
import re
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from photovault.catalog.library import LibraryQuery, count_library_items, library_asset_ids, library_day_counts, library_facets, list_library_items
from photovault.catalog.organization import add_assets_to_event, add_assets_to_topic_section, create_event, create_topic_section, delete_event, list_events, list_places, list_sources, list_tags, list_topic_sections, remove_assets_from_event, remove_assets_from_topic_section, update_event
from photovault.catalog.scanner import scan_volume
from photovault.catalog.people import list_people
from photovault.catalog.collections import list_collections
from photovault.catalog.thumbnail_jobs import build_missing_thumbnails, thumbnail_status
from photovault.backup.jobs import BackupJobManager
from photovault.database.connection import connect
from photovault.pairing.discovery import AndroidDiscoveryService
from photovault.pairing.trusted import list_trusted_android_devices, record_pairing_session, revoke_android_device, touch_android_device, trust_android_device
from photovault.sources.android_wifi import AndroidCompanionUnavailable, AndroidCompanionWifiSource
from photovault.collage.analysis import FaceBox, PhotoAnalysis, analyse_photo
from photovault.collage.poc.runner import run_poc_photos
from photovault.collage.models import Canvas, Cell, Crop, LayoutCandidate, PhotoInput, page_spec_from_dict
from photovault.collage.render import render_candidate
from photovault.collage.design_assets import (
    ALLOWED_MEDIA, MAX_PACKAGE_BYTES, read_asset_bytes, safe_member_name,
    sanitize_svg, sha256_bytes, validate_zip_members,
)
from photovault.collage.design_formats import (
    validate_and_repair_design_spec, validate_collage_document,
    validate_design_spec, to_collage_document, validate_page_spec,
)
from PIL import Image, ImageDraw, ImageFont, ImageOps

STATIC_ROOT = Path(__file__).with_name("static")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_ROOT = PROJECT_ROOT / "examples"
PACKAGE_ID_RE = re.compile(r"^pkg_[0-9a-f]{32}$")


def _package_manifest(catalog_path: Path, package_id: str) -> dict[str, object]:
    """Read a previously exported package without trusting any path from JSON."""
    if not PACKAGE_ID_RE.fullmatch(package_id):
        raise ValueError("package_id is invalid")
    root = (catalog_path.parent / "collage-design-packages").resolve()
    target = (root / f"{package_id}.zip").resolve()
    record = (root / f"{package_id}.json").resolve()
    if root not in target.parents or root not in record.parents or not (target.is_file() or record.is_file()):
        raise ValueError("design package was not found; export the package again")
    try:
        if record.is_file():
            package = json.loads(record.read_text(encoding="utf-8"))
        else:
            with zipfile.ZipFile(target) as archive:
                package = json.loads(archive.read("design-package.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise ValueError("design package is unreadable") from exc
    if not isinstance(package, dict) or package.get("package_id") != package_id:
        raise ValueError("design package identity does not match package_id")
    if str(package.get("catalog_id") or "") != catalog_path.stem:
        raise ValueError("design package belongs to a different catalog")
    assets = package.get("photo_assets") or package.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("design package has no assets")
    return package


def _managed_design_asset_ids(catalog_path: Path) -> set[str]:
    root = (catalog_path.parent / "collage-design-assets").resolve()
    if not root.is_dir():
        return set()
    return {path.stem for path in root.iterdir() if path.is_file() and path.stem.startswith("pa_")}


def _write_bytes_atomic(target: Path, raw: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
    temporary.replace(target)


def _decode_uploaded_package(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("package_zip_base64 is required")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("package_zip_base64 is invalid") from exc
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ValueError("design package is too large")
    return raw


def _ingest_design_package(catalog_path: Path, raw: bytes) -> tuple[dict[str, object], dict[str, Any], dict[str, Any]]:
    """Validate, sanitize and cache a v2 package before any document is written."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError("uploaded design package is not a valid ZIP") from exc
    with archive:
        names = set(validate_zip_members(archive, len(raw)))
        if not {"manifest.json", "design.json"}.issubset(names):
            raise ValueError("v2 design package must contain manifest.json and design.json")
        try:
            manifest = json.loads(archive.read("manifest.json"))
            design = json.loads(archive.read("design.json"))
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("design package JSON is unreadable") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != "PhotoManager AI Design Package" or int(manifest.get("schema_version", 0)) != 2:
            raise ValueError("unsupported design package manifest")
        if not isinstance(design, dict) or design.get("format") not in {"CollageDesignSpec", "PhotoManager Collage Design"} or int(design.get("schema_version", 0)) != 2:
            raise ValueError("design.json must be CollageDesignSpec v2")
        catalog_id = str(manifest.get("catalog_id") or design.get("catalog_id") or "")
        if catalog_id and catalog_id != catalog_path.stem:
            raise ValueError("design package belongs to a different catalog")
        photo_assets = design.get("assets")
        if not isinstance(photo_assets, list) or not photo_assets:
            raise ValueError("design.json must include photo asset references")
        package_assets = manifest.get("assets") or []
        if not isinstance(package_assets, list) or len(package_assets) > 40:
            raise ValueError("manifest.assets must be an array of at most 40 assets")
        package_id = "pkg_" + uuid.uuid4().hex
        decorative: list[dict[str, object]] = []
        pending: list[tuple[Path, bytes]] = []
        seen_ids: set[str] = set()
        total = 0
        for raw_asset in package_assets:
            if not isinstance(raw_asset, dict):
                raise ValueError("each manifest asset must be an object")
            asset_id = str(raw_asset.get("id") or "")
            if not re.fullmatch(r"^[A-Za-z0-9_-]{1,80}$", asset_id) or asset_id in seen_ids:
                raise ValueError("manifest asset ids must be unique safe names")
            seen_ids.add(asset_id)
            path = safe_member_name(str(raw_asset.get("path") or ""))
            suffix = Path(path).suffix.lower()
            if suffix not in ALLOWED_MEDIA or not path.startswith("assets/"):
                raise ValueError("decorative assets must be safe SVG, PNG or WebP files under assets/")
            expected_media = ALLOWED_MEDIA[suffix]
            if raw_asset.get("media_type") and str(raw_asset["media_type"]) != expected_media:
                raise ValueError(f"asset media_type does not match {path}")
            asset_bytes = read_asset_bytes(archive, path)
            total += len(asset_bytes)
            if total > 20 * 1024 * 1024:
                raise ValueError("decorative assets are too large")
            if raw_asset.get("sha256") and str(raw_asset["sha256"]).lower() != sha256_bytes(asset_bytes):
                raise ValueError(f"checksum mismatch for {path}")
            if suffix == ".svg":
                asset_bytes = sanitize_svg(asset_bytes)
            else:
                try:
                    with Image.open(io.BytesIO(asset_bytes)) as image:
                        image.verify()
                        if image.width > 12000 or image.height > 12000:
                            raise ValueError("decorative raster dimensions are too large")
                except (OSError, ValueError) as exc:
                    raise ValueError(f"decorative raster is unreadable: {path}") from exc
            managed_id = "pa_" + uuid.uuid4().hex
            target = (catalog_path.parent / "collage-design-assets" / f"{managed_id}{suffix}").resolve()
            root = (catalog_path.parent / "collage-design-assets").resolve()
            if root not in target.parents:
                raise ValueError("managed design asset path is invalid")
            pending.append((target, asset_bytes))
            decorative.append({"id": asset_id, "path": path, "media_type": expected_media, "sha256": sha256_bytes(asset_bytes), "package_asset_id": managed_id, "asset_url": f"/api/collage/design-assets/{managed_id}"})

        spec = json.loads(json.dumps(design))
        spec["package_id"] = package_id
        spec["catalog_id"] = catalog_path.stem
        photo_labels = {str(item.get("label")): str(item.get("asset_id")) for item in photo_assets if isinstance(item, dict) and item.get("label") and item.get("asset_id")}
        for alternative in spec.get("alternatives", []) if isinstance(spec.get("alternatives"), list) else []:
            for element in alternative.get("elements", []) if isinstance(alternative, dict) and isinstance(alternative.get("elements"), list) else []:
                if isinstance(element, dict) and element.get("type") == "photo" and str(element.get("asset_id") or "") in photo_labels:
                    element["asset_id"] = photo_labels[str(element["asset_id"])]
        by_path = {str(item["path"]): item for item in decorative}
        for alternative in spec.get("alternatives", []) if isinstance(spec.get("alternatives"), list) else []:
            for element in alternative.get("elements", []) if isinstance(alternative, dict) and isinstance(alternative.get("elements"), list) else []:
                if isinstance(element, dict) and element.get("type") == "design_asset":
                    ref = safe_member_name(str(element.get("asset_ref") or ""))
                    managed = by_path.get(ref)
                    if not managed:
                        raise ValueError(f"design asset reference is not listed in manifest: {ref}")
                    element["package_asset_id"] = managed["package_asset_id"]
                    element["asset_url"] = managed["asset_url"]
        connection = connect(catalog_path)
        try:
            available_photo_ids = {str(row[0]) for row in connection.execute("SELECT DISTINCT asset_id FROM asset_locations WHERE missing_since IS NULL")}
        finally:
            connection.close()
        photo_ids = {str(item["asset_id"]) for item in photo_assets if isinstance(item, dict) and item.get("asset_id")}
        missing_photo_ids = sorted(photo_ids - available_photo_ids)
        if missing_photo_ids:
            raise ValueError(f"unknown or unavailable photo asset ids: {', '.join(missing_photo_ids[:5])}")
        checked, report = validate_and_repair_design_spec(spec, available_photo_ids, {str(item["package_asset_id"]) for item in decorative})
        spec = checked
        package = {"format": "PhotoManager AI Design Package", "schema_version": 2, "package_id": package_id, "catalog_id": catalog_path.stem, "assets": photo_assets, "photo_assets": photo_assets, "decorative_assets": decorative, "page_spec": spec.get("page_spec"), "spec": spec, "validation": report}
        package_root = catalog_path.parent / "collage-design-packages"
        package_root.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        try:
            for target, asset_bytes in pending:
                _write_bytes_atomic(target, asset_bytes)
                written.append(target)
            _write_json_atomic(package_root / f"{package_id}.json", package)
        except Exception:
            for target in written:
                try:
                    target.unlink()
                except OSError:
                    pass
            raise
    asset_map = {str(item["asset_id"]): item for item in photo_assets if isinstance(item, dict) and item.get("asset_id")}
    asset_map.update({str(item["package_asset_id"]): item for item in decorative})
    return package, spec, asset_map


def _resolve_design_import(catalog_path: Path, payload: dict[str, object]) -> tuple[dict[str, object], dict[str, dict[str, object]], str | None]:
    """Resolve A-labels through the exported package before Python validation."""
    original = payload.get("spec") if isinstance(payload.get("spec"), dict) else payload
    if not isinstance(original, dict):
        raise ValueError("design spec must be an object")
    spec = json.loads(json.dumps(original))
    package_id = str(payload.get("package_id") or spec.get("package_id") or "").strip() or None
    inline_assets = spec.get("assets") if isinstance(spec.get("assets"), list) else []
    if package_id and not package_id.startswith("fixture:"):
        package = _package_manifest(catalog_path, package_id)
        assets = package.get("photo_assets") or package.get("assets")
        decorative = package.get("decorative_assets") if isinstance(package.get("decorative_assets"), list) else []
        spec["page_spec"] = spec.get("page_spec") or package.get("page_spec") or {}
    else:
        # Fixtures and older local exports may carry their manifest inline. A
        # normal AI import with a package_id always takes the package branch.
        assets = inline_assets
        decorative = []
    if not isinstance(assets, list) or not assets:
        raise ValueError("AI design must include a package_id from an exported design package")
    asset_items = [item for item in assets if isinstance(item, dict) and item.get("asset_id")]
    asset_map = {str(item["asset_id"]): item for item in asset_items}
    design_asset_map = {str(item["package_asset_id"]): item for item in decorative if isinstance(item, dict) and item.get("package_asset_id")}
    asset_map.update(design_asset_map)
    labels = {str(item.get("label")): str(item["asset_id"]) for item in asset_items if item.get("label")}
    spec["assets"] = asset_items
    if package_id:
        spec["package_id"] = package_id
    for alternative in spec.get("alternatives", []) if isinstance(spec.get("alternatives"), list) else []:
        for element in alternative.get("elements", []) if isinstance(alternative, dict) else []:
            if isinstance(element, dict) and element.get("type") == "photo":
                reference = str(element.get("asset_id", ""))
                if reference in labels:
                    element["asset_id"] = labels[reference]
            if isinstance(element, dict) and element.get("type") == "design_asset":
                reference = str(element.get("package_asset_id") or "")
                if reference not in design_asset_map:
                    asset_ref = str(element.get("asset_ref") or "")
                    match = next((item for item in decorative if isinstance(item, dict) and str(item.get("path")) == asset_ref), None)
                    if match:
                        reference = str(match["package_asset_id"])
                if reference in design_asset_map:
                    element["package_asset_id"] = reference
                    element["asset_url"] = design_asset_map[reference].get("asset_url")
    checked = validate_design_spec(spec, set(asset_map) - set(design_asset_map), set(design_asset_map))
    return checked, asset_map, package_id


def _write_json_atomic(target: Path, payload: object) -> None:
    """Publish a complete JSON document or leave the previous file untouched."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(payload, stream, indent=2, ensure_ascii=False, default=str)
        stream.flush()
    temporary.replace(target)


def _run_collage_job(httpd, catalog_path: Path, payload: dict[str, object], job_id: str) -> None:
    """Run candidate generation off the request thread and publish progress."""
    job = httpd.collage_jobs[job_id]
    job.update(status="running", stage="loading photos", progress=5)
    try:
        asset_ids = [str(value) for value in payload.get("asset_ids", []) if str(value)]
        connection = connect(catalog_path)
        try:
            photos = []
            for index, asset_id in enumerate(asset_ids):
                row = connection.execute("SELECT v.current_mount_path, al.relative_path FROM asset_locations al JOIN volumes v ON v.id=al.volume_id WHERE al.asset_id=? AND al.missing_since IS NULL AND v.status='CONNECTED' LIMIT 1", (asset_id,)).fetchone()
                if not row:
                    raise ValueError(f"photo is offline or missing: {asset_id}")
                root = Path(str(row[0])).resolve()
                path = (root / str(row[1])).resolve()
                if root not in path.parents or not path.is_file():
                    raise ValueError(f"photo is unavailable: {asset_id}")
                cache = getattr(httpd, "collage_analysis_cache")
                fingerprints = getattr(httpd, "collage_analysis_fingerprints")
                stat = path.stat()
                fingerprint = {"path": str(path), "size_bytes": stat.st_size, "modified_ns": stat.st_mtime_ns}
                if asset_id not in cache or fingerprints.get(asset_id) != fingerprint:
                    cache[asset_id] = replace(analyse_photo(path), photo_id=asset_id)
                    fingerprints[asset_id] = fingerprint
                    save_collage_analysis_cache(getattr(httpd, "collage_analysis_cache_path"), cache, fingerprints)
                photos.append(cache[asset_id])
                job.update(progress=5 + int((index + 1) / len(asset_ids) * 20), stage=f"analysed {index + 1}/{len(asset_ids)} photos")
        finally:
            connection.close()

        run_id = uuid.uuid4().hex
        output = (catalog_path.parent / "collage-runs" / run_id)
        output.mkdir(parents=True, exist_ok=True)
        requested_providers = payload.get("providers")
        providers = [str(value) for value in requested_providers] if isinstance(requested_providers, list) else None
        page_spec = page_spec_from_dict(payload.get("page_spec"))
        transforms = payload.get("photo_transforms") if isinstance(payload.get("photo_transforms"), dict) else None
        render_mode = str(payload.get("render_mode") or "funnel").strip().lower()
        if render_mode not in {"funnel", "view"}:
            raise ValueError("render_mode must be funnel or view")
        # Candidate generation always analyses the connected original files.
        # The mode controls the disposable gallery preview size; the editor's
        # View mode reloads originals for the final page export.
        preview_long_edge = 1200 if render_mode == "funnel" else 2400
        job.update(progress=30, stage="generating candidates", run_id=run_id)
        metrics = run_poc_photos(
            photos,
            output,
            seed=int(payload.get("seed", 42)),
            providers=providers,
            count=int(payload.get("count", 10)),
            source_run_id=run_id,
            page_spec=page_spec,
            photo_transforms=transforms,
            preview_long_edge=preview_long_edge,
            progress_callback=lambda progress, stage: job.update(progress=progress, stage=stage),
        )
        job.update(progress=90, stage="saving candidates")
        candidates = json.loads((output / "candidates.json").read_text())
        result = {"run_id": run_id, "timestamp": datetime.now(timezone.utc).isoformat(), "selected_asset_ids": asset_ids, "seed": int(payload.get("seed", 42)), "page_spec": page_spec.to_dict(), "render_mode": render_mode, "preview_long_edge": preview_long_edge, "metrics": metrics, "candidates": [{"document_id": c["document_id"], "provider": c["provider"], "candidate_number": c["candidate_number"], "seed": c["seed"], "rejected": c["rejected"], "rejection_reasons": c["rejection_reasons"], "preview": f"/api/collage/runs/{run_id}/previews/{c['provider']}-{c['candidate_number']:02d}-seed-{c['seed']}.jpg", "document": f"/api/collage/runs/{run_id}/documents/{c['document_id']}"} for c in candidates]}
        (output / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        getattr(httpd, "collage_runs")[run_id] = {"output": output, "payload": result}
        job.update(status="complete", stage="complete", progress=100, result=result)
    except Exception as error:  # surfaced through the job endpoint, not a hung request
        job.update(status="failed", stage="failed", error=str(error))


def load_collage_analysis_cache(path: Path) -> tuple[dict[str, PhotoInput], dict[str, dict[str, object]]]:
    """Load reusable analysis only when its stable asset/file fingerprint is retained."""
    photos: dict[str, PhotoInput] = {}
    fingerprints: dict[str, dict[str, object]] = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return photos, fingerprints
    for asset_id, entry in (payload.items() if isinstance(payload, dict) else ()):
        if not isinstance(entry, dict) or not isinstance(entry.get("photo"), dict):
            continue
        photo = entry["photo"]
        analysis_data = photo.get("analysis")
        if not isinstance(analysis_data, dict):
            continue
        faces = tuple(FaceBox(**face) for face in analysis_data.get("faces", []) if isinstance(face, dict))
        analysis = PhotoAnalysis(
            width=int(analysis_data.get("width", 0)), height=int(analysis_data.get("height", 0)),
            orientation=analysis_data.get("orientation"), faces=faces,
            salient_region=tuple(analysis_data.get("salient_region", (0.15, 0.15, 0.85, 0.85))),
            quality_score=float(analysis_data.get("quality_score", 0.0)),
            detector=str(analysis_data.get("detector", "none")),
            detection_ms=float(analysis_data.get("detection_ms", 0.0)),
        )
        photos[str(asset_id)] = PhotoInput(
            photo_id=str(asset_id), path=Path(str(photo.get("path", ""))),
            width=int(photo.get("width", analysis.width)), height=int(photo.get("height", analysis.height)),
            capture_datetime=photo.get("capture_datetime"), quality_score=float(photo.get("quality_score", 0.0)), analysis=analysis,
        )
        fingerprints[str(asset_id)] = {"path": entry.get("path"), "size_bytes": entry.get("size_bytes"), "modified_ns": entry.get("modified_ns")}
    return photos, fingerprints


def save_collage_analysis_cache(path: Path, photos: dict[str, PhotoInput], fingerprints: dict[str, dict[str, object]]) -> None:
    payload = {}
    for asset_id, photo in photos.items():
        analysis = photo.analysis.to_dict() if photo.analysis is not None else None
        payload[asset_id] = {"path": fingerprints[asset_id]["path"], "size_bytes": fingerprints[asset_id]["size_bytes"], "modified_ns": fingerprints[asset_id]["modified_ns"], "photo": {"path": str(photo.path), "width": photo.width, "height": photo.height, "capture_datetime": photo.capture_datetime, "quality_score": photo.quality_score, "analysis": analysis}}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _row_payload(row) -> dict[str, object]:
    absolute_path = None
    if row["current_mount_path"] and row["volume_status"] == "CONNECTED":
        absolute_path = str((Path(str(row["current_mount_path"])) / str(row["relative_path"])).resolve())
    return {
        "asset_id": row["asset_id"], "filename": row["filename"], "media_type": row["media_type"],
        "relative_path": row["relative_path"], "size_bytes": row["size_bytes"],
        "captured": row["display_captured"] or row["captured"],
        "source_id": row["source_id"], "source": row["source_name"],
        "volume": row["volume_name"], "volume_status": row["volume_status"],
        "thumbnail": f"/api/thumb/{row['asset_id']}" if row["thumbnail_path"] else None,
        "thumbnail_path": str(row["thumbnail_path"]) if row["thumbnail_path"] else None,
        "contains_raw": bool(row["paired_raw_asset_id"]),
        "paired_raw_asset_id": row["paired_raw_asset_id"],
        "paired_raw_filename": row["paired_raw_filename"],
        "absolute_path": absolute_path,
        "original_url": f"/api/original/{row['asset_id']}",
        "camera": " ".join(filter(None, (row["camera_make"], row["camera_model"]))) or None,
        "width": row["width"], "height": row["height"], "orientation": row["orientation"],
        "latitude": row["latitude"], "longitude": row["longitude"],
        "favourite": bool(row["is_favourite"]), "review_status": row["review_status"], "rating": row["rating"],
        "topics": row["event_names"], "tags": row["tag_names"], "places": row["place_names"] or row["inherited_place_names"],
        "people": row["person_names"],
    }


def library_payload(connection, query: LibraryQuery) -> dict[str, object]:
    page_query = type(query)(**{**query.__dict__, "limit": query.limit + 1})
    fetched_rows = list_library_items(connection, page_query)
    has_more = len(fetched_rows) > query.limit
    rows = fetched_rows[:query.limit]
    items = [_row_payload(row) for row in rows]
    months = library_facets(connection, query)
    days: dict[str, list[dict[str, object]]] = {}
    for item in items:
        captured = str(item.get("captured") or "")
        days.setdefault(captured[:10] if captured else "Undated", []).append(item)
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(last["display_captured"], last["asset_id"])
    years: dict[str, int] = {}
    for month in months:
        year = str(month["key"])[:4]
        years[year] = years.get(year, 0) + int(month["item_count"])
    next_offset = query.offset + len(rows) if has_more else None
    return {"total": count_library_items(connection, query), "items": items, "months": months, "years": [{"key": year, "label": year, "item_count": count} for year, count in years.items()], "days": days, "day_counts": library_day_counts(connection, query), "next_cursor": next_cursor, "next_offset": next_offset, "has_more": has_more}


def folder_asset_ids(connection, folder: str) -> list[str]:
    """Return active asset ids below a folder for bulk selection."""
    folder = folder.strip("/")
    if folder:
        rows = connection.execute(
            "SELECT DISTINCT asset_id FROM asset_locations "
            "WHERE missing_since IS NULL AND relative_path LIKE ? "
            "ORDER BY relative_path, asset_id",
            (folder + "/%",),
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT DISTINCT asset_id FROM asset_locations "
            "WHERE missing_since IS NULL ORDER BY asset_id"
        ).fetchall()
    return [str(row[0]) for row in rows]


def topics_payload(connection) -> dict[str, object]:
    """Return editable Topics for the local UI without exposing catalog internals."""
    topics = []
    places = {place.id: place.name for place in list_places(connection)}
    for event in list_events(connection):
        topics.append({
            "id": event.id,
            "name": event.name,
            "start_datetime": event.start_datetime,
            "end_datetime": event.end_datetime,
            "event_type": event.event_type,
            "description": event.description,
            "item_count": event.item_count,
            "is_suggested": event.is_suggested,
            "default_place_id": event.default_place_id,
            "default_place": places.get(event.default_place_id or ""),
        })
    return {"topics": topics, "places": [{"id": key, "name": value} for key, value in places.items()]}


def navigation_payload(connection) -> dict[str, object]:
    return {
        "people": [{"id": p.id, "name": p.display_name or "Unnamed person", "item_count": p.item_count} for p in list_people(connection)],
        "places": [{"id": p.id, "name": p.name, "item_count": p.item_count} for p in list_places(connection)],
        "tags": [{"id": t.id, "name": t.name, "item_count": t.item_count} for t in list_tags(connection)],
        "categories": [{"id": f"{row[0]}:{row[1]}", "name": row[1], "detail": row[0], "item_count": int(row[2])} for row in connection.execute("SELECT model, label, COUNT(DISTINCT asset_id) FROM image_categories GROUP BY model, label ORDER BY lower(label), model")],
        "sources": [{"id": row[0], "name": row[1], "item_count": int(row[7])} for row in list_sources(connection)],
        "collections": [{"id": c.id, "name": c.title, "kind": c.kind, "item_count": c.item_count} for c in list_collections(connection)],
    }


def registered_volumes_payload(connection) -> list[dict[str, object]]:
    """Return registered local folders that the web UI can refresh safely."""
    rows = connection.execute(
        """SELECT v.id, v.display_name, v.status, v.current_mount_path,
                  COUNT(DISTINCT al.asset_id) AS item_count
           FROM volumes v LEFT JOIN asset_locations al
             ON al.volume_id=v.id AND al.missing_since IS NULL
           GROUP BY v.id ORDER BY v.display_name"""
    ).fetchall()
    return [
        {
            "id": str(row[0]),
            "source_id": f"folder:{row[0]}",
            "display_name": str(row[1]),
            "status": str(row[2] or "UNKNOWN"),
            "mount_path": str(row[3]) if row[3] else None,
            "path_exists": bool(row[3]) and Path(str(row[3])).expanduser().is_dir(),
            "item_count": int(row[4] or 0),
        }
        for row in rows
    ]


def _start_thumbnail_job(server: ThreadingHTTPServer, catalog_path: Path) -> bool:
    """Start the shared resumable preview builder, returning False if busy."""
    lock = getattr(server, "thumbnail_job_lock", None)
    if lock is None:
        lock = threading.Lock()
        server.thumbnail_job_lock = lock  # type: ignore[attr-defined]
    with lock:
        current = getattr(server, "thumbnail_job", None)
        if current and current.get("status") == "running":
            return False
        job_id = "thumb_" + uuid.uuid4().hex
        server.thumbnail_job = {"job_id": job_id, "status": "running", "processed": 0, "generated": 0, "failed": 0}  # type: ignore[attr-defined]

    def run_job() -> None:
        connection = connect(catalog_path)
        try:
            result = build_missing_thumbnails(
                connection,
                cache_root=catalog_path.parent / ".photovault-thumbnails",
                retry_failed=True,
                progress=lambda value: setattr(server, "thumbnail_job", {"job_id": job_id, "status": "running", **value}),
            )
            server.thumbnail_job = {"job_id": job_id, "status": "cancelled" if result["cancelled"] else "complete", **result}  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            server.thumbnail_job = {"job_id": job_id, "status": "failed", "error": str(exc)}  # type: ignore[attr-defined]
        finally:
            connection.close()

    threading.Thread(target=run_job, daemon=True, name=f"thumbnail-job-{job_id[:8]}").start()
    return True


def _start_volume_refresh(server: ThreadingHTTPServer, catalog_path: Path, volume_id: str) -> dict[str, object]:
    """Queue an incremental folder scan and then build any missing thumbnails."""
    if not re.fullmatch(r"vol_[0-9a-f]{24}", volume_id):
        raise ValueError("invalid volume id")
    lock = getattr(server, "volume_refresh_lock", None)
    if lock is None:
        lock = threading.Lock()
        server.volume_refresh_lock = lock  # type: ignore[attr-defined]
    with lock:
        current = getattr(server, "volume_refresh_job", None)
        if current and current.get("status") in {"queued", "running"}:
            raise ValueError("a source refresh is already running")
        connection = connect(catalog_path)
        try:
            row = connection.execute(
                "SELECT id, display_name, current_mount_path FROM volumes WHERE id=?",
                (volume_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError("volume is not registered")
        root = Path(str(row[2] or "")).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"source folder is unavailable: {root}")
        job_id = "refresh_" + uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "volume_id": volume_id,
            "display_name": str(row[1]),
            "root": str(root),
            "status": "queued",
            "stage": "queued",
            "files_seen": 0,
            "files_catalogued": 0,
            "errors": 0,
            "thumbnail_job_started": False,
        }
        server.volume_refresh_job = job  # type: ignore[attr-defined]

    def run_refresh() -> None:
        running = dict(job, status="running", stage="scanning")
        server.volume_refresh_job = running  # type: ignore[attr-defined]
        connection = connect(catalog_path)
        try:
            result = scan_volume(connection, volume_id, root)
        except Exception as exc:  # noqa: BLE001
            server.volume_refresh_job = dict(running, status="failed", stage="failed", error=str(exc))  # type: ignore[attr-defined]
            return
        finally:
            connection.close()
        started = _start_thumbnail_job(server, catalog_path)
        completed = dict(running, status="complete", stage="complete", **result, thumbnail_job_started=started)
        server.volume_refresh_job = completed  # type: ignore[attr-defined]

    threading.Thread(target=run_refresh, daemon=True, name=f"volume-refresh-{job_id[:8]}").start()
    return dict(job)


class PhotoVaultHandler(BaseHTTPRequestHandler):
    server_version = "PhotoVaultLocal/0.1"

    @property
    def catalog_path(self) -> Path:
        return self.server.catalog_path  # type: ignore[attr-defined]

    def _send(self, body: bytes, content_type: str, status: int = 200, *, immutable: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: object, status: int = 200) -> None:
        self._send(json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        from photovault.web.culling import handle
        if handle(self, parsed, 'GET'):
            return
        if parsed.path.startswith("/api/backup/jobs/"):
            job_id = parsed.path.removeprefix("/api/backup/jobs/").strip("/")
            try:
                self._json(getattr(self.server, "backup_jobs").get(job_id).payload())
            except KeyError as exc:
                self._json({"error": str(exc)}, 404)
            return
        if parsed.path == "/api/library/ids":
            connection = connect(self.catalog_path)
            try:
                params = parse_qs(parsed.query)
                day = params.get("day", [""])[0]
                captured_from = params.get("from", [""])[0]
                captured_to = params.get("to", [""])[0]
                if day:
                    captured_from = f"{day} 00:00:00"
                    captured_to = f"{day} 23:59:59"
                query = LibraryQuery(
                    search=params.get("search", [""])[0],
                    folder_prefix=params.get("folder", [""])[0],
                    media_type=params.get("type", ["ALL"])[0].upper(),
                    favourite_only=params.get("favourite", ["0"])[0] == "1",
                    recently_added=params.get("recent", ["0"])[0] == "1",
                    captured_from=captured_from,
                    captured_to=captured_to,
                    captured_month=params.get("month", [""])[0],
                    source_id=params.get("source", [""])[0],
                    event_id=params.get("event", [""])[0],
                    tag_id=params.get("tag", [""])[0],
                    place_id=params.get("place", [""])[0],
                    person_id=params.get("person", [""])[0],
                    category=params.get("category", [""])[0],
                    review_status=params.get("review", [""])[0],
                    include_rejected=params.get("include_rejected", ["0"])[0] == "1",
                )
                asset_ids = library_asset_ids(connection, query)
                self._json({"day": day, "folder": query.folder_prefix.strip("/"), "asset_ids": asset_ids, "count": len(asset_ids)})
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, 400)
            finally:
                connection.close()
            return
        if parsed.path.startswith("/api/collage/jobs/"):
            job_id = parsed.path.removeprefix("/api/collage/jobs/").strip("/")
            job = getattr(self.server, "collage_jobs", {}).get(job_id)
            if job is None:
                self._json({"error": "collage job not found"}, 404)
            else:
                self._json(dict(job))
            return
        if parsed.path == "/api/collage/folders":
            connection = connect(self.catalog_path)
            try:
                folders: dict[str, int] = {}
                for row in connection.execute("SELECT relative_path FROM asset_locations WHERE missing_since IS NULL ORDER BY relative_path"):
                    path = str(row[0]); parts = path.split("/")[:-1]
                    if any(part.startswith(".") for part in parts):
                        continue
                    for depth in range(1, len(parts) + 1): folders["/".join(parts[:depth])] = folders.get("/".join(parts[:depth]), 0) + 1
                self._json({"folders": [{"name": name, "count": count} for name, count in sorted(folders.items())]})
            finally: connection.close()
            return
        if parsed.path == "/api/collage/topics":
            connection = connect(self.catalog_path)
            try:
                self._json({"topics": [{"id": topic.id, "name": topic.name, "item_count": topic.item_count} for topic in list_events(connection)]})
            finally: connection.close()
            return
        if parsed.path == "/api/collage/photos":
            params = parse_qs(parsed.query); folder = params.get("folder", [""])[0]; topic = params.get("topic", [""])[0]; source_ids = [value for value in params.get("source", []) if value]; requested_ids = tuple(value for value in params.get("asset_id", []) if value)
            connection = connect(self.catalog_path)
            try:
                if requested_ids:
                    self._json(library_payload(connection, LibraryQuery(asset_ids=requested_ids, media_type="IMAGE", limit=len(requested_ids))))
                elif len(source_ids) <= 1:
                    self._json(library_payload(connection, LibraryQuery(folder_prefix=folder, event_id=topic, source_id=source_ids[0] if source_ids else "", media_type="IMAGE", limit=200)))
                else:
                    merged = []
                    total = 0
                    for source_id in source_ids:
                        payload = library_payload(connection, LibraryQuery(folder_prefix=folder, event_id=topic, source_id=source_id, media_type="IMAGE", limit=200))
                        total += int(payload["total"])
                        merged.extend(payload["items"])
                    merged.sort(key=lambda item: (str(item.get("captured") or ""), str(item.get("asset_id") or "")), reverse=True)
                    self._json({"total": total, "items": merged[:200], "months": [], "years": [], "days": {}, "next_cursor": None, "has_more": total > 200})
            finally: connection.close()
            return
        if parsed.path.startswith("/api/collage/design-packages/"):
            package_id = parsed.path.removeprefix("/api/collage/design-packages/").strip("/")
            if not PACKAGE_ID_RE.fullmatch(package_id):
                self._json({"error": "invalid package id"}, 400)
                return
            target = (self.catalog_path.parent / "collage-design-packages" / f"{package_id}.zip").resolve()
            root = (self.catalog_path.parent / "collage-design-packages").resolve()
            if root not in target.parents or not target.is_file():
                self._send(b"Not found", "text/plain", 404)
                return
            self._send(target.read_bytes(), "application/zip", immutable=True)
            return
        if parsed.path.startswith("/api/collage/design-assets/"):
            managed_id = parsed.path.removeprefix("/api/collage/design-assets/").strip("/")
            if not re.fullmatch(r"pa_[0-9a-f]{32}", managed_id):
                self._json({"error": "invalid design asset id"}, 400)
                return
            root = (self.catalog_path.parent / "collage-design-assets").resolve()
            matches = [path for path in root.glob(f"{managed_id}.*") if path.is_file() and path.suffix.lower() in {".svg", ".png", ".webp"}] if root.is_dir() else []
            if not matches:
                self._send(b"Not found", "text/plain", 404)
                return
            target = matches[0].resolve()
            if root not in target.parents:
                self._send(b"Not found", "text/plain", 404)
                return
            self._send(target.read_bytes(), ALLOWED_MEDIA[target.suffix.lower()], immutable=True)
            return
        if parsed.path.startswith("/api/collage/documents/"):
            document_id = parsed.path.removeprefix("/api/collage/documents/").strip("/")
            if not re.fullmatch(r"doc_[0-9a-f]{32}", document_id):
                self._json({"error": "invalid document id"}, 400)
                return
            root = (self.catalog_path.parent / "collage-documents").resolve()
            target = (root / f"{document_id}.json").resolve()
            if root not in target.parents or not target.is_file():
                self._json({"error": "document not found"}, 404)
                return
            try:
                self._json(json.loads(target.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                self._json({"error": "document is unreadable"}, 500)
            return
        if parsed.path == "/api/collage/runs":
            runs = []
            for run_id, run in getattr(self.server, "collage_runs", {}).items():
                payload = run.get("payload", {})
                runs.append({"run_id": run_id, "timestamp": payload.get("timestamp"), "seed": payload.get("seed"), "selected_count": len(payload.get("selected_asset_ids", [])), "candidate_count": len(payload.get("candidates", []))})
            runs.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
            self._json({"runs": runs})
            return
        if parsed.path.startswith("/api/collage/runs/"):
            parts = parsed.path.split("/")
            run = getattr(self.server, "collage_runs", {}).get(parts[4])
            if run is None: self._send(b"Not found", "text/plain", 404); return
            if len(parts) == 5: self._json(run["payload"]); return
            if len(parts) == 6 and parts[5] == "comparison":
                target = (run["output"] / "crop-comparison.jpg").resolve()
                self._send(target.read_bytes(), "image/jpeg", immutable=True); return
            if len(parts) == 7 and parts[5] == "documents":
                document_id = parts[6]
                target = (run["output"] / "documents" / f"{document_id}.json").resolve()
                if run["output"] not in target.parents or not target.is_file(): self._send(b"Not found", "text/plain", 404); return
                payload = json.loads(target.read_text(encoding="utf-8"))
                self._json(payload[0] if isinstance(payload, list) and payload else payload)
                return
            target = (run["output"] / "previews" / parts[6]).resolve()
            if run["output"] not in target.parents or not target.is_file(): self._send(b"Not found", "text/plain", 404); return
            self._send(target.read_bytes(), mimetypes.guess_type(target.name)[0] or "image/jpeg", immutable=True); return
        if parsed.path == "/api/library":
            self._library(parsed.query)
            return
        if parsed.path == "/api/topics":
            connection = connect(self.catalog_path)
            try:
                self._json(topics_payload(connection))
            finally:
                connection.close()
            return
        if parsed.path.startswith("/api/topics/") and parsed.path.endswith("/sections"):
            topic_id = parsed.path.removeprefix("/api/topics/").removesuffix("/sections").strip("/")
            connection = connect(self.catalog_path)
            try: self._json({"topic_id": topic_id, "sections": list_topic_sections(connection, topic_id)})
            finally: connection.close()
            return
        if parsed.path.startswith("/api/sections/") and parsed.path.endswith("/assets"):
            section_id = parsed.path.removeprefix("/api/sections/").removesuffix("/assets").strip("/")
            connection = connect(self.catalog_path)
            try:
                rows = connection.execute("SELECT asset_id FROM topic_section_assets WHERE section_id=? ORDER BY sort_order, asset_id", (section_id,)).fetchall()
                self._json({"section_id": section_id, "asset_ids": [str(row[0]) for row in rows]})
            finally: connection.close()
            return
        if parsed.path == "/api/navigation":
            connection = connect(self.catalog_path)
            try:
                self._json(navigation_payload(connection))
            finally:
                connection.close()
            return
        if parsed.path == "/api/android/devices":
            discovery: AndroidDiscoveryService = getattr(self.server, "android_discovery")
            states: dict[str, str] = getattr(self.server, "android_connection_states")
            devices = []
            for d in discovery.devices:
                pairing, protocol, api_version = d.pairing, d.protocol, d.api_version
                status = states.get(d.device_id, "available")
                # TXT records can lag behind the phone's current pairing window.
                # Probe the public status endpoint so the UI never hides Pair
                # merely because mDNS still contains an older advertisement.
                try:
                    live = AndroidCompanionWifiSource(f"http://{d.host}:{d.port}", "", timeout=1.5)._json("/api/pair/status")
                    pairing = bool(live.get("pairing"))
                    protocol = str(live.get("protocol") or protocol)
                    api_version = "2" if pairing or protocol == "photovault-pairing-v1" else api_version
                    status = "available"
                except Exception:  # noqa: BLE001
                    status = states.get(d.device_id, "offline")
                devices.append({"device_id": d.device_id, "display_name": d.display_name, "host": d.host,
                                "port": d.port, "protocol": protocol, "api_version": api_version,
                                "pairing": pairing, "status": status})
            self._json({"devices": devices, "service": "_photovault._tcp.local"})
            return
        if parsed.path == "/api/android/trusted":
            connection = connect(self.catalog_path)
            try: self._json({"devices": list_trusted_android_devices(connection)})
            finally: connection.close()
            return
        if parsed.path == "/api/thumbnails/status":
            connection = connect(self.catalog_path)
            try:
                self._json(thumbnail_status(connection) | {"job": getattr(self.server, "thumbnail_job", None)})
            finally:
                connection.close()
            return
        if parsed.path == "/api/volumes":
            connection = connect(self.catalog_path)
            try:
                self._json({
                    "volumes": registered_volumes_payload(connection),
                    "refresh_job": getattr(self.server, "volume_refresh_job", None),
                })
            finally:
                connection.close()
            return
        if parsed.path.startswith("/api/original/"):
            self._original(parsed.path.removeprefix("/api/original/"))
            return
        if parsed.path.startswith("/api/thumb/"):
            self._thumbnail(parsed.path.removeprefix("/api/thumb/"))
            return
        relative = "index.html" if parsed.path in {"", "/"} else ("topic_workspace.html" if parsed.path == "/topic-workspace" else ("collage_v2.html" if parsed.path == "/experimental/collage" else ("fabric_spike_v2.html" if parsed.path == "/experimental/collage/fabric-v2" else ("fabric_spike.html" if parsed.path == "/experimental/collage/fabric" else parsed.path.removeprefix("/")))))
        if parsed.path.startswith("/examples/"):
            relative_example = parsed.path.removeprefix("/examples/")
            target = (EXAMPLES_ROOT / relative_example).resolve()
            if EXAMPLES_ROOT not in target.parents or not target.is_file():
                self._send(b"Not found", "text/plain", 404)
                return
            try:
                self._send(target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            except OSError:
                self._send(b"Not found", "text/plain", 404)
            return
        target = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT not in target.parents and target != STATIC_ROOT:
            self._send(b"Not found", "text/plain", 404)
            return
        try:
            body = target.read_bytes()
            if target.name == "collage_v2.html":
                body = body.replace(b"</body>", b'<script src="/collage_sources.js?v=20260903-3"></script><script src="/collage_runs.js?v=20260903-3"></script><script src="/collage_crop_debug.js?v=20260903-3"></script><script src="/collage_topic.js?v=20260903-3"></script><script src="/collage_topic_refresh.js?v=20260903-3"></script><script src="/collage_topic_guard.js?v=20260903-3"></script></body>')
                body = body.replace(b"</body>", b'<script src="/collage_topic_section.js?v=20260904-1"></script></body>')
            self._send(body, mimetypes.guess_type(target.name)[0] or "text/plain")
        except FileNotFoundError:
            self._send(b"Not found", "text/plain", 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        from photovault.web.culling import handle
        if handle(self, parsed, 'POST'):
            return
        try:
            package_limit = MAX_PACKAGE_BYTES * 2 if parsed.path == "/api/collage/design-import-packages" else 1_000_000
            payload = self._read_json(package_limit)
            if parsed.path == "/api/collage/generate":
                asset_ids = [str(value) for value in payload.get("asset_ids", []) if str(value)]
                if not 2 <= len(asset_ids) <= 20: raise ValueError("select between 2 and 20 photographs")
                job_id = uuid.uuid4().hex
                self.server.collage_jobs[job_id] = {"job_id": job_id, "status": "queued", "stage": "queued", "progress": 0}
                threading.Thread(target=_run_collage_job, args=(self.server, self.catalog_path, payload, job_id), daemon=True, name=f"collage-job-{job_id[:8]}").start()
                self._json({"job_id": job_id, "status": "queued"}, 202); return
            if parsed.path == "/api/collage/design-import-packages":
                package, spec, asset_map = _ingest_design_package(self.catalog_path, _decode_uploaded_package(payload.get("package_zip_base64")))
                alternatives = spec.get("alternatives") if isinstance(spec.get("alternatives"), list) else []
                counts = [{"alternative": index, "elements": len(item.get("elements", [])),
                           "photos": sum(isinstance(element, dict) and element.get("type") == "photo" for element in item.get("elements", [])),
                           "design_assets": sum(isinstance(element, dict) and element.get("type") == "design_asset" for element in item.get("elements", []))}
                          for index, item in enumerate(alternatives) if isinstance(item, dict)]
                self._json({"valid": True, "package_id": package["package_id"], "spec": spec, "alternatives": counts, "validation": package.get("validation", {}), "decorative_assets": package.get("decorative_assets", [])}, 201)
                return
            if parsed.path == "/api/collage/design-packages":
                asset_ids = list(dict.fromkeys(str(value) for value in payload.get("asset_ids", []) if str(value)))
                if not 1 <= len(asset_ids) <= 200:
                    raise ValueError("select between 1 and 200 photographs")
                page = validate_page_spec(payload.get("page_spec") or {})
                connection = connect(self.catalog_path)
                try:
                    manifest = library_payload(connection, LibraryQuery(asset_ids=tuple(asset_ids), media_type="IMAGE", limit=len(asset_ids)))
                finally:
                    connection.close()
                items_by_id = {str(item["asset_id"]): item for item in manifest["items"]}
                missing = [asset_id for asset_id in asset_ids if asset_id not in items_by_id]
                if missing:
                    raise ValueError(f"unknown or unavailable asset ids: {', '.join(missing[:5])}")
                package_id = "pkg_" + uuid.uuid4().hex
                root = self.catalog_path.parent / "collage-design-packages"
                root.mkdir(parents=True, exist_ok=True)
                package_assets = []
                for index, asset_id in enumerate(asset_ids):
                    item = items_by_id[asset_id]
                    # The package is safe to upload to an external AI. Local
                    # filesystem paths and local API URLs are deliberately not
                    # part of its manifest; the ZIP contains the thumbnails.
                    package_assets.append({
                        "label": f"A{index + 1:02d}", "asset_id": asset_id,
                        "filename": item.get("filename"), "media_type": item.get("media_type"),
                        "source_id": item.get("source_id"), "source": item.get("source"),
                        "relative_path": item.get("relative_path"), "size_bytes": item.get("size_bytes"),
                        "capture_datetime": item.get("captured"), "width": item.get("width"),
                        "height": item.get("height"), "orientation": item.get("orientation"),
                        "camera": item.get("camera"),
                        "analysis": {"faces": "unavailable", "saliency": "unavailable"},
                        "thumbnail_file": f"thumbnails/A{index + 1:02d}.jpg",
                    })
                style_intent = str(payload.get("style_intent") or payload.get("style") or "organic scrapbook")
                legacy_package = {"format": "PhotoManager DesignPackage", "schema_version": 1, "package_id": package_id,
                                  "catalog_id": self.catalog_path.stem, "page_spec": page, "mode": str(payload.get("mode", "from_scratch")),
                                  "style": style_intent, "assets": package_assets,
                                  "selection": {"topic_id": payload.get("topic_id"), "section_id": payload.get("section_id"), "asset_ids": asset_ids}}
                design_spec = {"format": "CollageDesignSpec", "schema_version": 2, "package_id": package_id,
                               "catalog_id": self.catalog_path.stem, "page_spec": page, "style": style_intent,
                               "style_intent": style_intent, "mode": str(payload.get("mode", "from_scratch")),
                               "assets": package_assets, "alternatives": []}
                manifest_v2 = {"format": "PhotoManager AI Design Package", "schema_version": 2,
                              "package_id": package_id, "catalog_id": self.catalog_path.stem,
                              "design": "design.json", "photo_assets": package_assets, "assets": [],
                              "selection": legacy_package["selection"], "style_intent": style_intent}
                decorative_package_assets = []
                decorative_files = {}
                if isinstance(payload.get("current_document"), dict):
                    legacy_package["current_document"] = payload["current_document"]
                    design_spec["current_document"] = payload["current_document"]
                    # Preserve already-imported decorative artwork as safe,
                    # managed package assets. Never follow a path from the
                    # browser payload; resolve only pa_* files under our own
                    # managed directory.
                    managed_root = (self.catalog_path.parent / "collage-design-assets").resolve()
                    seen_managed = set()
                    for element in payload["current_document"].get("elements", []):
                        if not isinstance(element, dict) or element.get("type") != "design_asset":
                            continue
                        managed_id = str(element.get("asset_id") or element.get("package_asset_id") or "")
                        if not re.fullmatch(r"pa_[0-9a-f]{32}", managed_id) or managed_id in seen_managed:
                            continue
                        candidates = [path for path in managed_root.glob(f"{managed_id}.*") if path.is_file() and path.suffix.lower() in ALLOWED_MEDIA]
                        if not candidates:
                            continue
                        source = candidates[0]
                        raw_asset = source.read_bytes()
                        if source.suffix.lower() == ".svg":
                            raw_asset = sanitize_svg(raw_asset)
                        package_asset_id = f"D{len(decorative_package_assets) + 1:02d}"
                        package_path = f"assets/{package_asset_id}{source.suffix.lower()}"
                        decorative_files[package_path] = raw_asset
                        decorative_package_assets.append({"id": package_asset_id, "path": package_path,
                                                          "media_type": ALLOWED_MEDIA[source.suffix.lower()],
                                                          "sha256": sha256_bytes(raw_asset)})
                        seen_managed.add(managed_id)
                manifest_v2["assets"] = decorative_package_assets
                contact = Image.new("RGB", (1000, max(120, ((len(asset_ids) + 5) // 6) * 180)), "#f5f2ed")
                draw = ImageDraw.Draw(contact)
                images: dict[str, bytes] = {}
                for index, asset_id in enumerate(asset_ids):
                    item = items_by_id[asset_id]; raw = b""
                    # Prefer the connected original while building package
                    # thumbnails so EXIF orientation is normalized before the
                    # safe, embedded copy is written. Offline assets fall back
                    # to the cached thumbnail and use the catalog orientation.
                    path = item.get("absolute_path") or item.get("thumbnail_path")
                    try:
                        with Image.open(str(path)) as source:
                            thumb = ImageOps.exif_transpose(source).convert("RGB")
                            if not item.get("absolute_path"):
                                orientation = int(item.get("orientation") or 1)
                                transpose = {
                                    2: Image.Transpose.FLIP_LEFT_RIGHT,
                                    3: Image.Transpose.ROTATE_180,
                                    4: Image.Transpose.FLIP_TOP_BOTTOM,
                                    5: Image.Transpose.TRANSPOSE,
                                    6: Image.Transpose.ROTATE_270,
                                    7: Image.Transpose.TRANSVERSE,
                                    8: Image.Transpose.ROTATE_90,
                                }.get(orientation)
                                if transpose is not None:
                                    thumb = thumb.transpose(transpose)
                            thumb.thumbnail((145, 135))
                            cell = Image.new("RGB", (150, 145), "white"); cell.paste(thumb, ((150-thumb.width)//2, 2));
                            x = (index % 6) * 165 + 5; y = (index // 6) * 180 + 5
                            contact.paste(cell, (x, y)); draw.text((x, y + 148), f"A{index + 1:02d} {item['filename'][:18]}", fill="#292521")
                            buf = io.BytesIO(); thumb.save(buf, format="JPEG", quality=88); raw = buf.getvalue()
                    except (OSError, ValueError):
                        pass
                    images[f"A{index + 1:02d}.jpg"] = raw
                instructions = """# Photo Manager AI Design Package v2

Design a professional scrapbook-style photo-book page using only the supplied
real photo asset labels (A01, A02, ...). Do not invent, redraw, or replace
photographs. Choose one or two hero images, preserve faces, use negative space,
and keep text inside the page safe margin. Use deliberate rotation and restrained
overlap. Decorative artwork may be supplied separately as safe SVG, PNG or WebP
files under assets/; reference those files with a design_asset element and its
asset_ref. Do not use scripts, HTML, remote URLs, or arbitrary SVG markup.

Return JSON only as CollageDesignSpec v2. Geometry is in millimetres. Use the
stable font roles serif, sans, script or display. Every element needs a unique
id, z_index, x_mm, y_mm, width_mm and height_mm. Use text_fit shrink_to_fit
for headings and wrap_and_shrink for notes. You may return 3-5 alternatives.
Include this package_id in your response and do not include original photo files.
"""
                schema_path = Path(__file__).resolve().parent.parent / "collage" / "schemas" / "design-spec-v2.json"
                schema = json.loads(schema_path.read_text(encoding="utf-8")) if schema_path.is_file() else {"format": "CollageDesignSpec", "schema_version": 2}
                schema_v1_path = Path(__file__).resolve().parent.parent / "collage" / "schemas" / "design-spec-v1.json"
                schema_v1 = json.loads(schema_v1_path.read_text(encoding="utf-8")) if schema_v1_path.is_file() else {"format": "CollageDesignSpec", "schema_version": 1}
                target = root / f"{package_id}.zip"
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("design-package.json", json.dumps(legacy_package, indent=2, default=str))
                    archive.writestr("manifest.json", json.dumps(manifest_v2, indent=2, default=str))
                    archive.writestr("design.json", json.dumps(design_spec, indent=2, default=str))
                    out = io.BytesIO(); contact.save(out, format="JPEG", quality=90); archive.writestr("contact-sheet.jpg", out.getvalue())
                    for name, raw in images.items():
                        if raw: archive.writestr(f"thumbnails/{name}", raw)
                    for name, raw in decorative_files.items():
                        archive.writestr(name, raw)
                    archive.writestr("collage-design.schema.json", json.dumps(schema, indent=2))
                    archive.writestr("collage-design-v1.schema.json", json.dumps(schema_v1, indent=2))
                    archive.writestr("CHATGPT-INSTRUCTIONS.md", instructions)
                    archive.writestr("README-for-AI.txt", instructions)
                    archive.writestr("README.txt", "Photo Manager AI Design Package v2. Photo references stay in the local catalog; only thumbnails, optional safe decorative assets, and design metadata are included. Original files and local absolute paths are not included.")
                    if isinstance(legacy_package.get("current_document"), dict): archive.writestr("current-layout.json", json.dumps(legacy_package["current_document"], indent=2))
                self._json({"package_id": package_id, "download": f"/api/collage/design-packages/{package_id}", "asset_count": len(asset_ids), "manifest": manifest_v2, "legacy_manifest": legacy_package}, 201)
                return
            if parsed.path in {"/api/collage/design-imports/validate", "/api/collage/design-imports"}:
                checked, asset_map, package_id = _resolve_design_import(self.catalog_path, payload)
                photo_ids = {asset_id for asset_id, item in asset_map.items() if not item.get("package_asset_id")}
                design_asset_ids = {asset_id for asset_id, item in asset_map.items() if item.get("package_asset_id")}
                checked, validation = validate_and_repair_design_spec(checked, photo_ids, design_asset_ids)
                if parsed.path.endswith("/validate"):
                    counts = [{"alternative": index, "elements": len(item["elements"]), "photos": sum(x["type"] == "photo" for x in item["elements"]), "design_assets": sum(x["type"] == "design_asset" for x in item["elements"])} for index, item in enumerate(checked["alternatives"])]
                    self._json({"valid": True, "warnings": validation["warnings"], "repairs": validation["repairs"], "validation": validation, "alternatives": counts, "package_id": package_id, "spec": checked})
                    return
                index = int(payload.get("alternative_index", 0))
                if index < 0 or index >= len(checked["alternatives"]): raise ValueError("alternative_index is out of range")
                document = to_collage_document(checked, index, asset_map)
                document["metadata"]["package_id"] = package_id
                document["metadata"]["layout_validation"] = validation
                document["metadata"]["source"] = f"CollageDesignSpec v{checked.get('schema_version', 1)}"
                document_root = self.catalog_path.parent / "collage-documents"
                document_path = document_root / f"{document['document_id']}.json"
                _write_json_atomic(document_path, document)
                self._json({"ok": True, "document": document, "document_url": f"/api/collage/documents/{document['document_id']}"}, 201)
                return
            if parsed.path == "/api/collage/documents":
                connection = connect(self.catalog_path)
                try:
                    available = {str(row[0]) for row in connection.execute("SELECT DISTINCT asset_id FROM asset_locations WHERE missing_since IS NULL")}
                finally:
                    connection.close()
                checked = validate_collage_document(payload, available, _managed_design_asset_ids(self.catalog_path))
                original_id = str(checked.get("document_id") or "")
                document = dict(checked)
                document["document_id"] = "doc_" + uuid.uuid4().hex
                if original_id:
                    document["parent_document_id"] = original_id
                document["modified_at"] = datetime.now(timezone.utc).isoformat()
                document["edited"] = True
                target = self.catalog_path.parent / "collage-documents" / f"{document['document_id']}.json"
                _write_json_atomic(target, document)
                self._json({"ok": True, "document": document, "document_url": f"/api/collage/documents/{document['document_id']}", "variant": True}, 201)
                return
            if parsed.path.startswith("/api/collage/runs/") and "/documents/" in parsed.path:
                parts = parsed.path.split("/")
                run_id, document_id = parts[4], parts[6]
                run = getattr(self.server, "collage_runs", {}).get(run_id)
                if run is None: self._json({"error": "run not found"}, 404); return
                if not isinstance(payload, dict) or payload.get("document_type") != "CollageDocument":
                    raise ValueError("payload must be a CollageDocument")
                if str(payload.get("document_id")) != document_id:
                    raise ValueError("document_id does not match URL")
                frames = payload.get("frames")
                if not isinstance(frames, list) or not frames:
                    raise ValueError("document must contain at least one frame")
                for frame in frames:
                    if not isinstance(frame, dict):
                        raise ValueError("every frame must be an object")
                original_document_id = document_id
                if not payload.get("edited"):
                    document_id = "doc_" + uuid.uuid4().hex
                    payload["parent_candidate_id"] = original_document_id
                payload["document_id"] = document_id
                payload["cells"] = frames
                payload["edited"] = True
                payload["modified_at"] = datetime.now(timezone.utc).isoformat()
                target = (run["output"] / "documents" / f"{document_id}.json").resolve()
                if run["output"] not in target.parents: self._json({"error": "invalid document path"}, 400); return
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                canvas_data = payload.get("canvas") or {}
                canvas = Canvas(
                    width=int(canvas_data.get("width", 1200)),
                    height=int(canvas_data.get("height", 800)),
                    gutter=int(canvas_data.get("gutter", 12)),
                )
                cells = []
                photos = {}
                connection = connect(self.catalog_path)
                try:
                    for frame in frames:
                        crop_data = frame.get("crop") or {}
                        cells.append(Cell(
                            photo_id=str(frame["photo_id"]), x=int(frame["x"]), y=int(frame["y"]),
                            width=int(frame["width"]), height=int(frame["height"]),
                            crop=Crop(float(crop_data.get("left", 0)), float(crop_data.get("top", 0)), float(crop_data.get("right", 1)), float(crop_data.get("bottom", 1)), str(crop_data.get("mode", "cover"))),
                            crop_metadata=dict(frame.get("crop_metadata") or {}),
                            transform=dict(frame.get("transform") or {}),
                        ))
                        row = connection.execute("""SELECT v.current_mount_path, al.relative_path
                            FROM asset_locations al JOIN volumes v ON v.id=al.volume_id
                            WHERE al.asset_id=? AND al.missing_since IS NULL AND v.status='CONNECTED'
                            ORDER BY al.id LIMIT 1""", (str(frame["photo_id"]),)).fetchone()
                        if row:
                            path = (Path(str(row[0])) / str(row[1])).resolve()
                            if path.is_file(): photos[str(frame["photo_id"])] = PhotoInput(str(frame["photo_id"]), path, 1, 1)
                finally:
                    connection.close()
                if set(photo.photo_id for photo in photos.values()) != {cell.photo_id for cell in cells if cell.photo_id}:
                    raise ValueError("one or more document photos are offline")
                candidate = LayoutCandidate(
                    provider=str(payload.get("provider", "edited")),
                    candidate_number=int(payload.get("candidate_number", 1)),
                    seed=int(payload.get("seed", 0)), canvas=canvas, cells=cells,
                    style=str(payload.get("style", "")), metadata=dict(payload.get("metadata") or {}),
                    edited=True, document_id=document_id, source_run_id=run_id,
                    modified_at=str(payload["modified_at"]), created_at=payload.get("created_at"),
                    page_spec=page_spec_from_dict(payload.get("page_spec")).to_dict(),
                )
                preview = run["output"] / "previews" / f"{candidate.provider}-{candidate.candidate_number:02d}-seed-{candidate.seed}-{document_id}.jpg"
                render_candidate(candidate, photos, preview)
                self._json({"ok": True, "document": payload, "document_url": f"/api/collage/runs/{run_id}/documents/{document_id}", "preview": f"/api/collage/runs/{run_id}/previews/{preview.name}?v={int(datetime.now().timestamp())}", "variant": document_id != original_document_id}); return
            if parsed.path in {"/api/android/pair", "/api/android/reconnect"} or parsed.path.startswith("/api/android/pair/"):
                if not self._local_origin_allowed():
                    self._json({"error": "pairing requests must originate from the Photo Manager local UI"}, 403)
                    return
                pairings: dict[str, AndroidCompanionWifiSource] = getattr(self.server, "android_pairings")
                if parsed.path == "/api/android/pair":
                    host = str(payload.get("host", "")).strip()
                    port = int(payload.get("port", 8765))
                    if not host or not (1 <= port <= 65535): raise ValueError("a valid discovered device host and port are required")
                    try:
                        source = AndroidCompanionWifiSource(f"http://{host}:{port}", "", timeout=10.0)
                        result = source.pair(desktop_name="Photo Manager")
                    except AndroidCompanionUnavailable:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        # Never let a downstream pairing failure close the browser socket.
                        raise AndroidCompanionUnavailable(f"pairing failed: {exc}") from exc
                    pairings[result["session_id"]] = source
                    connection = connect(self.catalog_path)
                    try: record_pairing_session(connection, session_id=result["session_id"], device_id=result["device_id"], display_name=result["display_name"], state="AWAITING_NUMERIC_CONFIRMATION", sas=result["sas"], public_key_fingerprint=result["fingerprint"])
                    finally: connection.close()
                    self._json({"ok": True, **result}, 202)
                    return
                if parsed.path == "/api/android/reconnect":
                    device_id = str(payload.get("device_id", "")).strip(); host = str(payload.get("host", "")).strip(); port = int(payload.get("port", 8765))
                    connection = connect(self.catalog_path)
                    try:
                        trusted = connection.execute("SELECT public_key_fingerprint FROM trusted_android_devices WHERE device_id=? AND revoked_at IS NULL", (device_id,)).fetchone()
                    finally: connection.close()
                    if not trusted: self._json({"error": "device is not trusted"}, 403); return
                    try:
                        result = AndroidCompanionWifiSource(f"http://{host}:{port}", "", timeout=10.0).reconnect(expected_android_fingerprint=str(trusted[0]))
                    except AndroidCompanionUnavailable:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        raise AndroidCompanionUnavailable(f"reconnect failed: {exc}") from exc
                    connection = connect(self.catalog_path)
                    try: touch_android_device(connection, device_id)
                    finally: connection.close()
                    self._json({"ok": True, **result}, 200)
                    return
                suffix = parsed.path.removeprefix("/api/android/pair/").strip("/")
                session_id = suffix.removesuffix("/confirm")
                source = pairings.get(session_id)
                if source is None: self._json({"error": "unknown pairing session"}, 404); return
                if suffix.endswith("/confirm"):
                    paired = source.confirm_pairing(session_id)
                    result = source.pairing_result(session_id)
                    source_id = None
                    if paired:
                        connection = connect(self.catalog_path)
                        try:
                            source_id = trust_android_device(connection, device_id=result["device_id"], display_name=result["display_name"], public_key_fingerprint=result["fingerprint"], credential_reference_id="desktop-noise-static-v1")
                            record_pairing_session(connection, session_id=session_id, device_id=result["device_id"], display_name=result["display_name"], state="PAIRED", sas=result["sas"], public_key_fingerprint=result["fingerprint"])
                        finally: connection.close()
                    self._json({"ok": True, "paired": paired, "source_id": source_id, "session_token": source.session_token if paired else None})
                    return
            jobs: BackupJobManager = getattr(self.server, "backup_jobs")
            if parsed.path == "/api/backup/jobs":
                folders = payload.get("folders", [])
                if isinstance(folders, str): folders = [folders]
                job = jobs.create(url=str(payload.get("url", "")), token=str(payload.get("token", "")), session_token=str(payload.get("session_token", "")) or None, android_fingerprint=str(payload.get("android_fingerprint", "")) or None, folders=[str(folder) for folder in folders], destination=str(payload.get("destination", "")), media_filter=str(payload.get("media_filter", "ALL")), workers=int(payload.get("workers", 5)), fsync_mode=str(payload.get("fsync_mode", "batch")), batch_files=int(payload.get("batch_files", 25)))
                self._json(job.payload(), 201)
                return
            if parsed.path.startswith("/api/backup/jobs/"):
                suffix = parsed.path.removeprefix("/api/backup/jobs/").strip("/").split("/")
                job = jobs.get(suffix[0])
                if len(suffix) != 2: self._json({"error": "Not found"}, 404); return
                if suffix[1] == "start": self._json(jobs.start(job.id).payload(), 202); return
                if suffix[1] == "cancel": self._json(jobs.cancel(job.id).payload()); return
                self._json({"error": "Not found"}, 404); return
            connection = connect(self.catalog_path)
            try:
                if parsed.path == "/api/thumbnails/build":
                    if not _start_thumbnail_job(self.server, self.catalog_path):
                        self._json({"error": "thumbnail generation is already running"}, 409)
                        return
                    self._json({"ok": True, "status": "running"}, 202)
                    return
                volume_refresh_prefix = "/api/volumes/"
                if parsed.path.startswith(volume_refresh_prefix) and parsed.path.endswith("/refresh"):
                    volume_id = parsed.path.removeprefix(volume_refresh_prefix).removesuffix("/refresh").strip("/")
                    job = _start_volume_refresh(self.server, self.catalog_path, volume_id)
                    self._json(job, 202)
                    return
                if parsed.path == "/api/topics":
                    event_id = create_event(
                        connection,
                        str(payload.get("name", "")),
                        start_datetime=_date_value(payload.get("start_date")),
                        end_datetime=_date_value(payload.get("end_date")),
                        event_type=str(payload.get("event_type", "other")),
                        description=str(payload.get("description", "")),
                        default_place_id=_optional_value(payload.get("default_place_id")),
                    )
                    self._json({"ok": True, "id": event_id}, 201)
                    return
                if parsed.path.startswith("/api/topics/") and parsed.path.endswith("/sections"):
                    topic_id = parsed.path.removeprefix("/api/topics/").removesuffix("/sections").strip("/")
                    asset_ids = payload.get("asset_ids", [])
                    if not isinstance(asset_ids, list): raise ValueError("asset_ids must be a list")
                    section_id = create_topic_section(connection, topic_id, str(payload.get("title", "")), [str(item) for item in asset_ids], description=str(payload.get("description", "")), date_start=_date_value(payload.get("date_start")), date_end=_date_value(payload.get("date_end")), cover_asset_id=_optional_value(payload.get("cover_asset_id")))
                    self._json({"ok": True, "id": section_id}, 201)
                    return
                if parsed.path.startswith("/api/sections/") and parsed.path.endswith("/assets"):
                    section_id = parsed.path.removeprefix("/api/sections/").removesuffix("/assets").strip("/")
                    asset_ids = payload.get("asset_ids", [])
                    if not isinstance(asset_ids, list): raise ValueError("asset_ids must be a list")
                    self._json({"ok": True, "added": add_assets_to_topic_section(connection, section_id, [str(item) for item in asset_ids])})
                    return
                prefix = "/api/topics/"
                if parsed.path.startswith(prefix) and parsed.path.endswith("/assets"):
                    event_id = parsed.path[len(prefix):-len("/assets")].strip("/")
                    asset_ids = payload.get("asset_ids", [])
                    if not isinstance(asset_ids, list):
                        raise ValueError("asset_ids must be a list")
                    added = add_assets_to_event(connection, event_id, [str(item) for item in asset_ids])
                    self._json({"ok": True, "added": added})
                    return
                self._json({"error": "Not found"}, 404)
            finally:
                connection.close()
        except AndroidCompanionUnavailable as exc:
            self._json({"error": str(exc)}, 502)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            # Keep local UI/API failures observable instead of returning an empty socket.
            self.log_error("POST %s failed: %s", parsed.path, exc)
            self._json({"error": "internal server error"}, 500)

    def _local_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin: return False
        port = self.server.server_port
        return origin in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        prefix = "/api/topics/"
        if not parsed.path.startswith(prefix):
            self._json({"error": "Not found"}, 404)
            return
        event_id = parsed.path[len(prefix):].strip("/")
        try:
            payload = self._read_json()
            connection = connect(self.catalog_path)
            try:
                update_event(
                    connection,
                    event_id,
                    name=str(payload.get("name", "")),
                    start_datetime=_date_value(payload.get("start_date")),
                    end_datetime=_date_value(payload.get("end_date")),
                    event_type=str(payload.get("event_type", "other")),
                    description=str(payload.get("description", "")),
                    default_place_id=_optional_value(payload.get("default_place_id")),
                )
                self._json({"ok": True, "id": event_id})
            finally:
                connection.close()
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)

    def do_DELETE(self) -> None:  # noqa: N802
        if self.path.startswith("/api/android/trusted/"):
            if not self._local_origin_allowed(): self._json({"error": "request must originate from the Photo Manager local UI"}, 403); return
            device_id = urlparse(self.path).path.removeprefix("/api/android/trusted/").strip("/")
            connection = connect(self.catalog_path)
            try: revoke_android_device(connection, device_id); self._json({"ok": True, "device_id": device_id})
            finally: connection.close()
            return
        parsed = urlparse(self.path)
        section_prefix = "/api/sections/"
        if parsed.path.startswith(section_prefix) and parsed.path.endswith("/assets"):
            section_id = parsed.path.removeprefix(section_prefix).removesuffix("/assets").strip("/")
            try:
                payload = self._read_json()
                asset_ids = payload.get("asset_ids", [])
                if not isinstance(asset_ids, list):
                    raise ValueError("asset_ids must be a list")
                connection = connect(self.catalog_path)
                try:
                    removed = remove_assets_from_topic_section(connection, section_id, [str(item) for item in asset_ids])
                    self._json({"ok": True, "removed": removed})
                finally:
                    connection.close()
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, 400)
            return
        prefix = "/api/topics/"
        if not parsed.path.startswith(prefix):
            self._json({"error": "Not found"}, 404)
            return
        suffix = parsed.path[len(prefix):].strip("/").split("/")
        try:
            payload = self._read_json() if suffix[-1:] == ["assets"] else {}
            connection = connect(self.catalog_path)
            try:
                if len(suffix) == 2 and suffix[1] == "assets":
                    asset_ids = payload.get("asset_ids", [])
                    if not isinstance(asset_ids, list):
                        raise ValueError("asset_ids must be a list")
                    removed = remove_assets_from_event(connection, suffix[0], [str(item) for item in asset_ids])
                    self._json({"ok": True, "removed": removed})
                elif len(suffix) == 1:
                    delete_event(connection, suffix[0])
                    self._json({"ok": True, "id": suffix[0]})
                else:
                    self._json({"error": "Not found"}, 404)
            finally:
                connection.close()
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)

    def _read_json(self, max_bytes: int = 1_000_000) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > max_bytes:
            raise ValueError("request body is too large")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _library(self, raw_query: str) -> None:
        params = parse_qs(raw_query)
        month = params.get("month", [""])[0]
        day = params.get("day", [""])[0]
        captured_from = params.get("from", [""])[0]
        captured_to = params.get("to", [""])[0]
        if day:
            captured_from = f"{day} 00:00:00"
            captured_to = f"{day} 23:59:59"
        search = params.get("search", [""])[0]
        media_type = params.get("type", ["ALL"])[0].upper()
        event_id = params.get("event", [""])[0]
        recently_added = params.get("recent", ["0"])[0] == "1"
        review_status = params.get("review", [""])[0]
        favourite_only = params.get("favourite", ["0"])[0] == "1"
        tag_id = params.get("tag", [""])[0]
        place_id = params.get("place", [""])[0]
        person_id = params.get("person", [""])[0]
        category = params.get("category", [""])[0]
        source_id = params.get("source", [""])[0]
        folder = params.get("folder", [""])[0]
        include_rejected = params.get("include_rejected", ["0"])[0] == "1"
        sort = params.get("sort", ["captured_desc_id"])[0]
        limit = min(max(int(params.get("limit", [150])[0]), 1), 200)
        offset = max(int(params.get("offset", [0])[0]), 0)
        cursor = _decode_cursor(params.get("cursor", [""])[0])
        connection = connect(self.catalog_path)
        try:
            self._json(library_payload(connection, LibraryQuery(search=search, media_type=media_type, captured_month=month, captured_from=captured_from, captured_to=captured_to, folder_prefix=folder, event_id=event_id, recently_added=recently_added, review_status=review_status, favourite_only=favourite_only, tag_id=tag_id, place_id=place_id, person_id=person_id, category=category, source_id=source_id, include_rejected=include_rejected, sort=sort, limit=limit, offset=offset, after_captured=cursor[0], after_asset_id=cursor[1])))
        except (ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, 400)
        finally:
            connection.close()

    def _thumbnail(self, asset_id: str) -> None:
        connection = connect(self.catalog_path)
        try:
            row = connection.execute(
                """SELECT th.path, al.filename, al.relative_path,
                          v.current_mount_path, v.status
                   FROM thumbnails th
                   JOIN asset_locations al ON al.asset_id=th.asset_id AND al.missing_since IS NULL
                   JOIN volumes v ON v.id=al.volume_id
                   WHERE th.asset_id=? AND th.version='v1-320'
                   ORDER BY CASE WHEN v.status='CONNECTED' THEN 0 ELSE 1 END
                   LIMIT 1""",
                (asset_id,),
            ).fetchone()
            if not row or not row[0]:
                self._send(b"Not found", "text/plain", 404)
                return
            path = Path(str(row[0]))
            if not path.is_file():
                self._send(b"Not found", "text/plain", 404)
                return
            # Some catalogues contain a tiny 160x120 RAW IFD thumbnail. For a
            # RAW-only asset, prefer the camera's embedded full JPEG so the
            # grid remains useful; paired RAW assets never reach this endpoint
            # because the shared library predicate exposes their JPEG instead.
            if str(row[1]).lower().endswith((".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw", ".3fr", ".iiq")) and row[3] and row[4] == "CONNECTED":
                root = Path(str(row[3])).resolve()
                target = (root / str(row[2])).resolve()
                if root in target.parents and target.is_file():
                    from photovault.web.culling import _raw_embedded_jpeg
                    embedded = _raw_embedded_jpeg(target)
                    if embedded:
                        try:
                            import io
                            from PIL import Image, ImageOps
                            with Image.open(io.BytesIO(embedded)) as raw_image:
                                image = ImageOps.exif_transpose(raw_image)
                                image.thumbnail((320, 320))
                                output = io.BytesIO()
                                image.convert("RGB").save(output, format="JPEG", quality=84, optimize=True)
                            self._send(output.getvalue(), "image/jpeg")
                            return
                        except (OSError, ValueError):
                            pass
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "image/jpeg")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()
            with path.open("rb") as stream:
                while chunk := stream.read(64 * 1024):
                    self.wfile.write(chunk)
        finally:
            connection.close()

    def _original(self, asset_id: str) -> None:
        """Serve an original only when its catalogued volume is connected."""
        connection = connect(self.catalog_path)
        try:
            row = connection.execute(
                """SELECT v.current_mount_path, v.status, al.relative_path
                   FROM asset_locations al JOIN volumes v ON v.id=al.volume_id
                   WHERE al.asset_id=? AND al.missing_since IS NULL
                   ORDER BY CASE WHEN v.status='CONNECTED' THEN 0 ELSE 1 END, al.id
                   LIMIT 1""", (asset_id,)
            ).fetchone()
            if not row or row[1] != "CONNECTED" or not row[0]:
                self._send(b"Original is offline", "text/plain; charset=utf-8", 409)
                return
            root = Path(str(row[0])).resolve()
            path = (root / str(row[2])).resolve()
            if (path != root and root not in path.parents) or not path.is_file():
                self._send(b"Original is unavailable", "text/plain; charset=utf-8", 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("Content-Disposition", f'inline; filename="{path.name.replace(chr(34), "")}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with path.open("rb") as stream:
                while chunk := stream.read(256 * 1024):
                    self.wfile.write(chunk)
        finally:
            connection.close()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _optional_value(value: object) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _date_value(value: object) -> str | None:
    clean = _optional_value(value)
    if clean and len(clean) != 10:
        raise ValueError("dates must use YYYY-MM-DD")
    return clean


def _encode_cursor(captured: object, asset_id: object) -> str:
    raw = json.dumps([captured or "", str(asset_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[str, str]:
    if not value:
        return "", ""
    try:
        padded = value + "=" * (-len(value) % 4)
        captured, asset_id = json.loads(base64.urlsafe_b64decode(padded))
        return str(captured), str(asset_id)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValueError("invalid cursor")


def serve(catalog: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the local UI. Defaults to loopback so the catalog is not exposed to LAN."""
    httpd = ThreadingHTTPServer((host, port), PhotoVaultHandler)
    httpd.catalog_path = catalog.expanduser().resolve()  # type: ignore[attr-defined]
    httpd.backup_jobs = BackupJobManager(httpd.catalog_path)  # type: ignore[attr-defined]
    httpd.android_discovery = AndroidDiscoveryService()  # type: ignore[attr-defined]
    httpd.android_pairings = {}  # type: ignore[attr-defined]
    httpd.android_connection_states = {}  # type: ignore[attr-defined]
    httpd.collage_runs = {}  # type: ignore[attr-defined]
    httpd.collage_jobs = {}  # type: ignore[attr-defined]
    httpd.thumbnail_job_lock = threading.Lock()  # type: ignore[attr-defined]
    httpd.volume_refresh_lock = threading.Lock()  # type: ignore[attr-defined]
    httpd.volume_refresh_job = None  # type: ignore[attr-defined]
    httpd.collage_analysis_cache_path = httpd.catalog_path.parent / "collage-analysis-cache.json"  # type: ignore[attr-defined]
    httpd.collage_analysis_cache, httpd.collage_analysis_fingerprints = load_collage_analysis_cache(httpd.collage_analysis_cache_path)  # type: ignore[attr-defined]
    # Runs are file-backed so a server restart does not erase the candidate
    # gallery or its editable CollageDocuments.
    run_root = httpd.catalog_path.parent / "collage-runs"
    if run_root.is_dir():
        for run_json in run_root.glob("*/run.json"):
            try:
                payload = json.loads(run_json.read_text(encoding="utf-8"))
                run_id = str(payload.get("run_id") or run_json.parent.name)
                httpd.collage_runs[run_id] = {"output": run_json.parent, "payload": payload}  # type: ignore[attr-defined]
            except (OSError, ValueError, TypeError):
                # A partial run must not prevent the local server from
                # starting; its directory remains available for inspection.
                continue
    def reconnect_discovered(change, device) -> None:
        if change == "disappeared":
            httpd.android_connection_states[device.device_id] = "offline"  # type: ignore[attr-defined]
            return
        if change not in {"appeared", "updated"}: return
        def run() -> None:
            connection = connect(httpd.catalog_path)
            try: trusted = connection.execute("SELECT public_key_fingerprint FROM trusted_android_devices WHERE device_id=? AND revoked_at IS NULL", (device.device_id,)).fetchone()
            finally: connection.close()
            if not trusted: return
            try:
                AndroidCompanionWifiSource(f"http://{device.host}:{device.port}", "").reconnect(expected_android_fingerprint=str(trusted[0]))
                httpd.android_connection_states[device.device_id] = "connected"  # type: ignore[attr-defined]
            except AndroidCompanionUnavailable:
                httpd.android_connection_states[device.device_id] = "offline"  # type: ignore[attr-defined]
        threading.Thread(target=run, daemon=True, name="photovault-android-reconnect").start()
    httpd.android_discovery.on_change = reconnect_discovered  # type: ignore[attr-defined]
    httpd.android_discovery.start()  # type: ignore[attr-defined]
    print(f"PhotoVault web UI: http://{host}:{port}")
    try:
        httpd.serve_forever()
    finally:
        httpd.android_discovery.stop()  # type: ignore[attr-defined]
        httpd.server_close()
