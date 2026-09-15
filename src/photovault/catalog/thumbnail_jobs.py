"""Resumable, catalog-backed thumbnail generation jobs."""
from __future__ import annotations

import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .thumbnails import generate_thumbnail

VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".webm"}


def thumbnail_status(connection) -> dict[str, int]:
    row = connection.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN t.asset_id IS NOT NULL THEN 1 ELSE 0 END) AS ready,
                  SUM(CASE WHEN t.asset_id IS NULL AND f.asset_id IS NOT NULL THEN 1 ELSE 0 END) AS failed,
                  SUM(CASE WHEN t.asset_id IS NULL AND f.asset_id IS NULL THEN 1 ELSE 0 END) AS pending
           FROM assets a
           LEFT JOIN thumbnails t ON t.asset_id=a.id AND t.version='v1-320'
           LEFT JOIN thumbnail_failures f ON f.asset_id=a.id"""
    ).fetchone()
    return {key: int(row[key] or 0) for key in ("total", "ready", "failed", "pending")}


def _video_thumbnail(source: Path, destination: Path) -> Path | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-ss", "2", "-i", str(source), "-frames:v", "1", "-vf", "scale=320:320:force_original_aspect_ratio=decrease", str(destination)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    return destination if completed.returncode == 0 and destination.is_file() else None


def build_missing_thumbnails(connection, *, cache_root: Path, limit: int = 0, cancel: threading.Event | None = None, progress: Callable[[dict[str, int]], None] | None = None, retry_failed: bool = False) -> dict[str, int | bool]:
    """Process missing previews in 200-row batches; one bad file never stops the job."""
    result: dict[str, int | bool] = {"processed": 0, "generated": 0, "failed": 0, "cancelled": False}
    cache_root = cache_root.expanduser().resolve()
    # A retry may include failures that existed before this invocation, but
    # must not select a failure recorded by this same invocation again.  The
    # latter would make the batch loop retry the same broken asset forever.
    retry_started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    failed_filter = "AND (f.asset_id IS NULL OR f.failed_at < ?)" if retry_failed else "AND f.asset_id IS NULL"
    while True:
        if cancel and cancel.is_set():
            result["cancelled"] = True
            break
        batch_size = min(200, limit - int(result["processed"])) if limit else 200
        if batch_size <= 0:
            break
        query = f"""SELECT DISTINCT a.id, a.media_type, al.relative_path, v.current_mount_path
                FROM assets a JOIN asset_locations al ON al.asset_id=a.id
                JOIN volumes v ON v.id=al.volume_id
                LEFT JOIN thumbnails t ON t.asset_id=a.id AND t.version='v1-320'
                LEFT JOIN thumbnail_failures f ON f.asset_id=a.id
                WHERE al.missing_since IS NULL AND t.asset_id IS NULL {failed_filter}
                ORDER BY COALESCE(al.capture_date, datetime(al.modified_ns / 1000000000, 'unixepoch')) DESC, al.asset_id
                LIMIT ?"""
        query_params = (retry_started_at, batch_size) if retry_failed else (batch_size,)
        rows = connection.execute(query, query_params).fetchall()
        if not rows:
            break
        for row in rows:
            if cancel and cancel.is_set():
                result["cancelled"] = True
                break
            asset_id, media_type, relative_path, mount_path = map(str, row)
            source = Path(mount_path) / relative_path
            output = None
            try:
                if source.is_file() and source.suffix.lower() in VIDEO_SUFFIXES:
                    output = _video_thumbnail(source, cache_root / f"{asset_id}_v1-320.jpg")
                    if output:
                        from PIL import Image
                        with Image.open(output) as image:
                            connection.execute("INSERT INTO thumbnails(asset_id, version, path, width, height, created_at) VALUES (?, 'v1-320', ?, ?, ?, ?) ON CONFLICT(asset_id, version) DO UPDATE SET path=excluded.path, width=excluded.width, height=excluded.height", (asset_id, str(output), image.width, image.height, datetime.now(timezone.utc).isoformat(timespec="seconds")))
                elif source.is_file():
                    output = generate_thumbnail(connection, asset_id, source, cache_root)
                if output:
                    connection.execute("DELETE FROM thumbnail_failures WHERE asset_id=?", (asset_id,))
                    result["generated"] += 1
                else:
                    connection.execute("INSERT OR REPLACE INTO thumbnail_failures(asset_id, reason, failed_at) VALUES (?, ?, ?)", (asset_id, "source file is unavailable or unsupported", datetime.now(timezone.utc).isoformat(timespec="seconds")))
                    result["failed"] += 1
            except Exception as exc:  # noqa: BLE001
                connection.execute("INSERT OR REPLACE INTO thumbnail_failures(asset_id, reason, failed_at) VALUES (?, ?, ?)", (asset_id, f"{type(exc).__name__}: {exc}", datetime.now(timezone.utc).isoformat(timespec="seconds")))
                result["failed"] += 1
            result["processed"] += 1
            if progress:
                progress({key: int(value) for key, value in result.items() if isinstance(value, int)})
        connection.commit()
        if result["cancelled"]:
            break
    connection.commit()
    return result
