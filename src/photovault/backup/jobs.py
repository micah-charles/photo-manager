"""Shared background backup jobs used by CLI, Web UI, and MCP adapters."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from photovault.backup.android_profiles import finish_android_backup_snapshot, missing_from_source, start_android_backup_snapshot, upsert_android_backup_profile
from photovault.backup.source_import import ImportCancelled, SourceImportItem, import_source_items, plan_source_import
from photovault.catalog.scanner import register_volume
from photovault.database.connection import connect
from photovault.sources.android_wifi import AndroidCompanionWifiSource


@dataclass
class BackupJob:
    id: str
    catalog: Path
    url: str
    token: str
    folders: tuple[str, ...]
    destination: Path
    session_token: str | None = None
    android_fingerprint: str | None = None
    media_filter: str = "ALL"
    workers: int = 5
    fsync_mode: str = "batch"
    batch_files: int = 25
    status: str = "PLANNED"
    planned_items: int = 0
    planned_bytes: int = 0
    imported_items: int = 0
    already_imported: int = 0
    failed_items: int = 0
    imported_bytes: int = 0
    current_speed: float = 0.0
    average_speed: float = 0.0
    interval_seconds: float = 0.0
    interval_files: int = 0
    interval_bytes: int = 0
    started_at: float | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def payload(self) -> dict[str, Any]:
        with self.lock:
            elapsed = time.monotonic() - self.started_at if self.started_at else 0.0
            return {"job_id": self.id, "status": self.status, "folders": list(self.folders),
                    "destination": str(self.destination), "media_filter": self.media_filter,
                    "secure_session": bool(self.session_token),
                    "android_fingerprint": self.android_fingerprint,
                    "workers": self.workers, "fsync_mode": self.fsync_mode, "batch_files": self.batch_files,
                    "planned_items": self.planned_items, "planned_bytes": self.planned_bytes,
                    "imported_items": self.imported_items, "already_imported": self.already_imported,
                    "failed_items": self.failed_items, "imported_bytes": self.imported_bytes,
                    "current_speed": self.current_speed, "average_speed": self.average_speed,
                    "interval_seconds": self.interval_seconds, "interval_files": self.interval_files,
                    "interval_bytes": self.interval_bytes, "elapsed_seconds": elapsed,
                    "error": self.error, "recent_events": list(self.events[-20:])}


class BackupJobManager:
    """Owns bounded, cancellable Android Wi-Fi backup jobs for one process."""

    def __init__(self, catalog: Path):
        self.catalog = catalog.expanduser().resolve()
        self._jobs: dict[str, BackupJob] = {}
        self._lock = threading.Lock()

    def create(self, *, url: str, token: str, folders: list[str], destination: str,
               session_token: str | None = None,
               android_fingerprint: str | None = None,
               media_filter: str = "ALL", workers: int = 5, fsync_mode: str = "batch",
               batch_files: int = 25) -> BackupJob:
        normalized = tuple(dict.fromkeys(folder.strip("/") for folder in folders if folder.strip("/")))
        destination_path = Path(destination).expanduser().resolve()
        if not normalized:
            raise ValueError("at least one source folder is required")
        if not destination_path.is_dir():
            raise ValueError("destination must be an existing directory")
        if media_filter not in {"ALL", "IMAGE", "VIDEO"}:
            raise ValueError("media_filter must be ALL, IMAGE or VIDEO")
        if not 1 <= int(workers) <= 8:
            raise ValueError("workers must be between 1 and 8")
        job = BackupJob("backup_job_" + uuid.uuid4().hex, self.catalog, url, token, normalized, destination_path,
                        session_token=session_token, android_fingerprint=android_fingerprint,
                        media_filter=media_filter, workers=int(workers),
                        fsync_mode=fsync_mode, batch_files=int(batch_files))
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> BackupJob:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"unknown backup job: {job_id}")
        return job

    def start(self, job_id: str) -> BackupJob:
        job = self.get(job_id)
        with job.lock:
            if job.status not in {"PLANNED", "CANCELLED", "FAILED"}:
                raise ValueError(f"job is already {job.status}")
            job.status = "RUNNING"; job.error = None; job.cancel_event.clear(); job.started_at = time.monotonic()
            job.events.append({"stage": "started", "at": time.time()})
        threading.Thread(target=self._run, args=(job,), daemon=True, name=f"{job.id}-runner").start()
        return job

    def cancel(self, job_id: str) -> BackupJob:
        job = self.get(job_id)
        job.cancel_event.set()
        with job.lock:
            if job.status == "PLANNED": job.status = "CANCELLED"
            job.events.append({"stage": "cancel_requested", "at": time.time()})
        return job

    def _run(self, job: BackupJob) -> None:
        connection = None
        snapshot_id = None
        try:
            source = AndroidCompanionWifiSource(job.url, job.token, session_token=job.session_token, expected_android_fingerprint=job.android_fingerprint)
            import_items: list[SourceImportItem] = []
            for folder in job.folders:
                for item in source.iter_folder(folder):
                    if job.media_filter != "ALL" and item.media_type != job.media_filter: continue
                    import_items.append(SourceImportItem(item.object_id, f"{folder}/{item.name}", item.size_bytes, media_type=item.media_type, modified_at=item.modified_at))
            connection = connect(job.catalog)
            destination_volume = register_volume(connection, job.destination)
            decisions = plan_source_import(connection, source, import_items, job.destination, destination_volume)
            conflicts = sum(d.status.value == "CONFLICT" for d in decisions)
            if conflicts: raise ValueError(f"{conflicts} destination conflict(s); no files copied")
            with job.lock:
                job.planned_items = len(decisions); job.planned_bytes = sum(i.size_bytes or 0 for i in import_items)
                job.already_imported = sum(d.status.value == "ALREADY_IMPORTED" for d in decisions)
                job.events.append({"stage":"planned", "items":job.planned_items, "bytes":job.planned_bytes, "already_imported":job.already_imported, "at":time.time()})
            profile_id = upsert_android_backup_profile(connection, source_id=source.identity().source_id, name="Web/MCP Android backup", folder_paths=job.folders, media_filter=job.media_filter, destination_volume_id=destination_volume, workers=job.workers, fsync_mode=job.fsync_mode, batch_files=job.batch_files)
            snapshot_id = start_android_backup_snapshot(connection, profile_id, planned_items=len(decisions), planned_bytes=job.planned_bytes)
            last_time = time.monotonic(); last_bytes = 0; last_files = 0
            def progress(row: dict[str, Any]) -> None:
                nonlocal last_time, last_bytes, last_files
                now = time.monotonic(); job.imported_items += 1; job.imported_bytes += int(row.get("bytes_written", 0))
                interval = now - last_time; delta = job.imported_bytes - last_bytes; files = job.imported_items - last_files
                with job.lock:
                    job.current_speed = delta / interval if interval else 0.0; job.average_speed = job.imported_bytes / max(now - (job.started_at or now), 0.001); job.interval_seconds = interval; job.interval_bytes = delta; job.interval_files = files
                    job.events.append({"stage":"progress", "files":job.imported_items, "bytes":job.imported_bytes, "interval_seconds":interval, "interval_bytes":delta, "interval_files":files, "interval_speed":job.current_speed, "average_speed":job.average_speed, "at":time.time()})
                if interval >= 5: last_time, last_bytes, last_files = now, job.imported_bytes, job.imported_items
            result = import_source_items(connection, source, import_items, job.destination, destination_volume, progress_callback=progress, fsync_mode=job.fsync_mode, batch_files=job.batch_files, workers=job.workers, cancel_callback=job.cancel_event.is_set, retry_attempts=2)
            job.already_imported = int(result["already_imported"])
            finish_android_backup_snapshot(connection, snapshot_id, status="COMPLETED", imported_items=int(result["imported"]), already_imported_items=job.already_imported, imported_bytes=job.imported_bytes, details={"job_id":job.id})
            with job.lock: job.status = "COMPLETED"; job.events.append({"stage":"completed", "at":time.time()})
        except ImportCancelled as exc:
            if connection and snapshot_id: finish_android_backup_snapshot(connection, snapshot_id, status="CANCELLED", imported_items=job.imported_items, already_imported_items=job.already_imported, imported_bytes=job.imported_bytes, details={"job_id":job.id})
            with job.lock: job.status="CANCELLED"; job.error=str(exc); job.events.append({"stage":"cancelled", "at":time.time()})
        except Exception as exc:
            if connection and snapshot_id: finish_android_backup_snapshot(connection, snapshot_id, status="FAILED", imported_items=job.imported_items, already_imported_items=job.already_imported, failed_items=1, imported_bytes=job.imported_bytes, details={"job_id":job.id, "error":str(exc)})
            with job.lock: job.status="FAILED"; job.error=str(exc); job.events.append({"stage":"failed", "error":str(exc), "at":time.time()})
        finally:
            if connection: connection.close()
