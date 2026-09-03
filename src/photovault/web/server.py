"""Small dependency-free local web server for the PhotoVault Library UI."""
from __future__ import annotations

import json
import mimetypes
import base64
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from photovault.catalog.library import LibraryQuery, count_library_items, library_facets, list_library_items
from photovault.catalog.organization import add_assets_to_event, create_event, delete_event, list_events, list_places, list_sources, list_tags, remove_assets_from_event, update_event
from photovault.catalog.people import list_people
from photovault.catalog.collections import list_collections
from photovault.catalog.thumbnail_jobs import build_missing_thumbnails, thumbnail_status
from photovault.backup.jobs import BackupJobManager
from photovault.database.connection import connect
from photovault.pairing.discovery import AndroidDiscoveryService
from photovault.pairing.trusted import list_trusted_android_devices, record_pairing_session, revoke_android_device, touch_android_device, trust_android_device
from photovault.sources.android_wifi import AndroidCompanionUnavailable, AndroidCompanionWifiSource
from photovault.collage.analysis import analyse_photo
from photovault.collage.poc.runner import run_poc_photos
from photovault.collage.models import Canvas, Cell, Crop, LayoutCandidate, PhotoInput
from photovault.collage.render import render_candidate

STATIC_ROOT = Path(__file__).with_name("static")


def _row_payload(row) -> dict[str, object]:
    return {
        "asset_id": row["asset_id"], "filename": row["filename"], "media_type": row["media_type"],
        "relative_path": row["relative_path"], "size_bytes": row["size_bytes"],
        "captured": row["display_captured"] or row["captured"],
        "source_id": row["source_id"], "source": row["source_name"],
        "volume": row["volume_name"], "volume_status": row["volume_status"],
        "thumbnail": f"/api/thumb/{row['asset_id']}" if row["thumbnail_path"] else None,
        "camera": " ".join(filter(None, (row["camera_make"], row["camera_model"]))) or None,
        "width": row["width"], "height": row["height"], "latitude": row["latitude"], "longitude": row["longitude"],
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
    return {"total": count_library_items(connection, query), "items": items, "months": months, "years": [{"key": year, "label": year, "item_count": count} for year, count in years.items()], "days": days, "next_cursor": next_cursor, "has_more": has_more}


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
                folder = parse_qs(parsed.query).get("folder", [""])[0]
                asset_ids = folder_asset_ids(connection, folder)
                self._json({"folder": folder.strip("/"), "asset_ids": asset_ids, "count": len(asset_ids)})
            finally:
                connection.close()
            return
        if parsed.path == "/api/collage/folders":
            connection = connect(self.catalog_path)
            try:
                folders: dict[str, int] = {}
                for row in connection.execute("SELECT relative_path FROM asset_locations WHERE missing_since IS NULL ORDER BY relative_path"):
                    path = str(row[0]); parts = path.split("/")[:-1]
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
            params = parse_qs(parsed.query); folder = params.get("folder", [""])[0]; topic = params.get("topic", [""])[0]; source_ids = [value for value in params.get("source", []) if value]
            connection = connect(self.catalog_path)
            try:
                if len(source_ids) <= 1:
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
        if parsed.path.startswith("/api/original/"):
            self._original(parsed.path.removeprefix("/api/original/"))
            return
        if parsed.path.startswith("/api/thumb/"):
            self._thumbnail(parsed.path.removeprefix("/api/thumb/"))
            return
        relative = "index.html" if parsed.path in {"", "/"} else ("collage_v2.html" if parsed.path == "/experimental/collage" else parsed.path.removeprefix("/"))
        target = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT not in target.parents and target != STATIC_ROOT:
            self._send(b"Not found", "text/plain", 404)
            return
        try:
            body = target.read_bytes()
            if target.name == "collage_v2.html":
                body = body.replace(b"</body>", b'<script src="/collage_topic.js?v=20260903-1"></script><script src="/collage_topic_refresh.js?v=20260903-1"></script><script src="/collage_topic_guard.js?v=20260903-1"></script></body>')
            self._send(body, mimetypes.guess_type(target.name)[0] or "text/plain")
        except FileNotFoundError:
            self._send(b"Not found", "text/plain", 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/collage/generate":
                asset_ids = [str(value) for value in payload.get("asset_ids", []) if str(value)]
                if not 2 <= len(asset_ids) <= 20: raise ValueError("select between 2 and 20 photographs")
                connection = connect(self.catalog_path)
                try:
                    photos = []
                    for asset_id in asset_ids:
                        row = connection.execute("SELECT v.current_mount_path, al.relative_path FROM asset_locations al JOIN volumes v ON v.id=al.volume_id WHERE al.asset_id=? AND al.missing_since IS NULL AND v.status='CONNECTED' LIMIT 1", (asset_id,)).fetchone()
                        if not row: raise ValueError(f"photo is offline or missing: {asset_id}")
                        root = Path(str(row[0])).resolve(); path = (root / str(row[1])).resolve()
                        if root not in path.parents or not path.is_file(): raise ValueError(f"photo is unavailable: {asset_id}")
                        cache = getattr(self.server, "collage_analysis_cache")
                        if asset_id not in cache or cache[asset_id].path != path:
                            # Analysis may use a filename internally, but the
                            # persisted collage document must use PhotoVault's
                            # stable asset ID so duplicate filenames across
                            # sources never collide.
                            cache[asset_id] = replace(analyse_photo(path), photo_id=asset_id)
                        photos.append(cache[asset_id])
                finally: connection.close()
                run_id = uuid.uuid4().hex
                output = (self.catalog_path.expanduser().resolve().parent / "collage-runs" / run_id)
                output.mkdir(parents=True, exist_ok=True)
                requested_providers = payload.get("providers")
                providers = [str(value) for value in requested_providers] if isinstance(requested_providers, list) else None
                metrics = run_poc_photos(photos, output, seed=int(payload.get("seed", 42)), providers=providers, count=int(payload.get("count", 10)), source_run_id=run_id)
                candidates = json.loads((output / "candidates.json").read_text())
                result = {"run_id": run_id, "timestamp": datetime.now(timezone.utc).isoformat(), "selected_asset_ids": asset_ids, "seed": int(payload.get("seed", 42)), "metrics": metrics, "candidates": [{"document_id": c["document_id"], "provider": c["provider"], "candidate_number": c["candidate_number"], "seed": c["seed"], "rejected": c["rejected"], "rejection_reasons": c["rejection_reasons"], "preview": f"/api/collage/runs/{run_id}/previews/{c['provider']}-{c['candidate_number']:02d}-seed-{c['seed']}.jpg", "document": f"/api/collage/runs/{run_id}/documents/{c['document_id']}"} for c in candidates]}
                (output / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                getattr(self.server, "collage_runs")[run_id] = {"output": output, "payload": result}
                self._json(result, 201); return
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
                    current = getattr(self.server, "thumbnail_job", None)
                    if current and current.get("status") == "running":
                        self._json({"error": "thumbnail generation is already running"}, 409)
                        return
                    self.server.thumbnail_job = {"status": "running", "processed": 0, "generated": 0, "failed": 0}  # type: ignore[attr-defined]
                    catalog_path = self.catalog_path
                    job_server = self.server

                    def run_job() -> None:
                        connection = connect(catalog_path)
                        try:
                            result = build_missing_thumbnails(
                                connection,
                                cache_root=catalog_path.parent / ".photovault-thumbnails",
                                retry_failed=True,
                                progress=lambda value: setattr(job_server, "thumbnail_job", {"status": "running", **value}),
                            )
                            job_server.thumbnail_job = {"status": "cancelled" if result["cancelled"] else "complete", **result}  # type: ignore[attr-defined]
                        except Exception as exc:  # noqa: BLE001
                            job_server.thumbnail_job = {"status": "failed", "error": str(exc)}  # type: ignore[attr-defined]
                        finally:
                            connection.close()

                    threading.Thread(target=run_job, daemon=True).start()
                    self._json({"ok": True, "status": "running"}, 202)
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

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("request body is too large")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _library(self, raw_query: str) -> None:
        params = parse_qs(raw_query)
        month = params.get("month", [""])[0]
        captured_from = params.get("from", [""])[0]
        captured_to = params.get("to", [""])[0]
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
        limit = min(max(int(params.get("limit", [150])[0]), 1), 200)
        cursor = _decode_cursor(params.get("cursor", [""])[0])
        connection = connect(self.catalog_path)
        try:
            self._json(library_payload(connection, LibraryQuery(search=search, media_type=media_type, captured_month=month, captured_from=captured_from, captured_to=captured_to, folder_prefix=folder, event_id=event_id, recently_added=recently_added, review_status=review_status, favourite_only=favourite_only, tag_id=tag_id, place_id=place_id, person_id=person_id, category=category, source_id=source_id, include_rejected=include_rejected, sort="captured_desc_id", limit=limit, after_captured=cursor[0], after_asset_id=cursor[1])))
        except (ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, 400)
        finally:
            connection.close()

    def _thumbnail(self, asset_id: str) -> None:
        connection = connect(self.catalog_path)
        try:
            row = connection.execute(
                "SELECT th.path FROM thumbnails th WHERE th.asset_id=? AND th.version='v1-320' LIMIT 1", (asset_id,)
            ).fetchone()
            if not row or not row[0]:
                self._send(b"Not found", "text/plain", 404)
                return
            path = Path(str(row[0]))
            if not path.is_file():
                self._send(b"Not found", "text/plain", 404)
                return
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
    httpd.collage_analysis_cache = {}  # type: ignore[attr-defined]
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
