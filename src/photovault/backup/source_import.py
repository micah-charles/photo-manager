from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, Callable
import sqlite3
import uuid
from datetime import datetime, timezone

from photovault.catalog.sources import register_source
from photovault.catalog.scanner import utc_now
from photovault.catalog.hashing import sha256_file
from photovault.sources.base import ReadablePhotoSource


class ImportCancelled(RuntimeError):
    """A caller-requested interruption that leaves an atomic partial for resume."""


@dataclass(frozen=True)
class SourceImportItem:
    object_id: str
    relative_path: str
    size_bytes: int | None
    expected_sha256: str | None = None
    media_type: str = "IMAGE"
    modified_at: datetime | None = None


class SourceImportStatus(StrEnum):
    NEW = "NEW"
    ALREADY_IMPORTED = "ALREADY_IMPORTED"
    CONFLICT = "CONFLICT"


def start_import_batch(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    destination_volume_id: str,
    planned_items: int,
    planned_bytes: int = 0,
    details: dict[str, object] | None = None,
) -> str:
    """Record one user-visible import run before any destination bytes publish."""
    batch_id = "import_batch_" + uuid.uuid4().hex
    connection.execute(
        """INSERT INTO import_batches(
            id, source_id, destination_volume_id, started_at, status,
            planned_items, details_json
        ) VALUES (?, ?, ?, ?, 'RUNNING', ?, ?)""",
        (
            batch_id,
            source_id,
            destination_volume_id,
            utc_now(),
            planned_items,
            json.dumps({"planned_bytes": planned_bytes, **(details or {})}, sort_keys=True),
        ),
    )
    connection.commit()
    return batch_id


def finish_import_batch(
    connection: sqlite3.Connection,
    batch_id: str,
    *,
    status: str,
    imported_items: int = 0,
    already_imported_items: int = 0,
    failed_items: int = 0,
    imported_bytes: int = 0,
    details: dict[str, object] | None = None,
) -> None:
    """Close a batch with durable counters and a terminal status."""
    if status not in {"COMPLETED", "CANCELLED", "FAILED"}:
        raise ValueError("invalid import batch status")
    connection.execute(
        """UPDATE import_batches SET completed_at=?, status=?, imported_items=?,
           already_imported_items=?, failed_items=?, imported_bytes=?, details_json=?
           WHERE id=?""",
        (
            utc_now(), status, imported_items, already_imported_items, failed_items,
            imported_bytes, json.dumps(details or {}, sort_keys=True), batch_id,
        ),
    )
    connection.commit()


def list_import_batches(
    connection: sqlite3.Connection,
    *,
    source_id: str | None = None,
    destination_volume_id: str | None = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    """Return recent import runs for activity/history pages."""
    if limit < 1:
        raise ValueError("limit must be positive")
    clauses: list[str] = []
    params: list[object] = []
    if source_id is not None:
        clauses.append("b.source_id=?")
        params.append(source_id)
    if destination_volume_id is not None:
        clauses.append("b.destination_volume_id=?")
        params.append(destination_volume_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    return list(connection.execute(
        f"""SELECT b.*, s.display_name AS source_name,
                  v.display_name AS destination_volume_name
           FROM import_batches b
           JOIN source_profiles s ON s.source_id=b.source_id
           JOIN volumes v ON v.id=b.destination_volume_id
           {where}
           ORDER BY b.started_at DESC LIMIT ?""",
        params,
    ))


@dataclass(frozen=True)
class SourceImportDecision:
    item: SourceImportItem
    status: SourceImportStatus
    reason: str


def _safe_destination(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("source path escapes destination root")
    return candidate


def plan_source_import(
    connection: sqlite3.Connection,
    source: ReadablePhotoSource,
    items: list[SourceImportItem],
    destination_root: Path,
    destination_volume_id: str,
) -> list[SourceImportDecision]:
    """Classify source items without reading phone bytes or changing files."""
    identity = source.identity()
    register_source(connection, identity)
    decisions: list[SourceImportDecision] = []
    for item in items:
        destination = _safe_destination(destination_root, item.relative_path)
        existing = connection.execute(
            """
            SELECT source_size_bytes, source_modified_at, sha256
            FROM source_imports
            WHERE source_id=? AND logical_path=? AND destination_volume_id=?
            ORDER BY imported_at DESC LIMIT 1
            """,
            (identity.source_id, item.relative_path, destination_volume_id),
        ).fetchone()
        modified = item.modified_at.isoformat() if hasattr(item.modified_at, "isoformat") else None
        if existing and destination.exists() and existing[0] == item.size_bytes and existing[1] == modified and existing[2] and sha256_file(destination) == existing[2]:
            decisions.append(SourceImportDecision(item, SourceImportStatus.ALREADY_IMPORTED, "matching verified import exists"))
        elif destination.exists():
            decisions.append(SourceImportDecision(item, SourceImportStatus.CONFLICT, "destination exists but is not a matching completed import"))
        else:
            decisions.append(SourceImportDecision(item, SourceImportStatus.NEW, "no matching completed import exists"))
    return decisions


def stream_source_to_file(
    source: ReadablePhotoSource,
    item: SourceImportItem,
    destination_root: Path,
    *,
    fsync_file: bool = True,
    cancel_callback: Callable[[], bool] | None = None,
) -> dict[str, int | float | str]:
    """Stream one source object through bounded memory into an atomic destination.

    A Companion source that advertises ``range_read`` resumes a retained partial
    file after a transport interruption.  The partial is re-hashed before the
    request is resumed, so it is never trusted merely because its filename
    matches.  Size/hash validation failures remove the partial; transient I/O
    failures deliberately retain it for the next attempt.
    """
    destination = _safe_destination(destination_root, item.relative_path)
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".photomanager-partial")

    digest = hashlib.sha256()
    resumed_bytes = 0
    if partial.exists():
        if "range_read" not in source.capabilities():
            raise RuntimeError(f"partial import requires range-read support: {partial}")
        resumed_bytes = partial.stat().st_size
        if item.size_bytes is not None and resumed_bytes > item.size_bytes:
            partial.unlink()
            raise ValueError(f"partial exceeds expected source size: {resumed_bytes} > {item.size_bytes}")
        with partial.open("rb") as existing:
            while chunk := existing.read(256 * 1024):
                digest.update(chunk)
    bytes_written = resumed_bytes
    started = time.monotonic()
    try:
        if cancel_callback is not None and cancel_callback():
            raise ImportCancelled("import cancelled before stream started")
        with partial.open("ab" if resumed_bytes else "xb") as output:
            class HashingSink:
                def write(self, data: bytes) -> int:
                    nonlocal bytes_written
                    if cancel_callback is not None and cancel_callback():
                        raise ImportCancelled("import cancelled during stream")
                    digest.update(data)
                    bytes_written += len(data)
                    return output.write(data)

            if resumed_bytes:
                # The protocol only requires stream_object; Companion sources
                # additionally expose HTTP Range through this optional offset.
                metrics = source.stream_object(item.object_id, HashingSink(), offset=resumed_bytes)
            else:
                metrics = source.stream_object(item.object_id, HashingSink())
            output.flush()
            if fsync_file:
                os.fsync(output.fileno())
        actual_hash = digest.hexdigest()
        if item.size_bytes is not None and bytes_written != item.size_bytes:
            raise ValueError(f"source size mismatch: expected {item.size_bytes}, got {bytes_written}")
        if item.expected_sha256 is not None and actual_hash != item.expected_sha256:
            raise ValueError(f"source SHA-256 mismatch: expected {item.expected_sha256}, got {actual_hash}")
        if destination.exists():
            raise FileExistsError(f"destination appeared during import: {destination}")
        os.replace(partial, destination)
        # Originals are sent byte-for-byte, preserving embedded EXIF/XMP/GPS and
        # all container metadata. Also restore the filesystem modification time
        # where the destination filesystem permits it.
        if item.modified_at is not None:
            modified = item.modified_at
            if modified.tzinfo is None:
                modified = modified.replace(tzinfo=timezone.utc)
            try:
                os.utime(destination, (modified.timestamp(), modified.timestamp()))
            except OSError:
                pass
        return {
            "object_id": item.object_id,
            "destination": str(destination),
            "bytes_written": bytes_written,
            "resumed_bytes": resumed_bytes,
            "sha256": actual_hash,
            "elapsed_seconds": time.monotonic() - started,
            "source_bytes_per_second": metrics.get("bytes_per_second", 0.0),
        }
    except ValueError:
        # A completed-but-invalid payload must never be resumed or published.
        if partial.exists():
            partial.unlink()
        raise


def restore_import_modified_times(
    connection: sqlite3.Connection,
    destination_root: Path,
    destination_volume_id: str,
) -> dict[str, int]:
    """Best-effort restoration of source mtime for already verified imports."""
    restored = missing = unavailable = 0
    rows = connection.execute(
        "SELECT destination_relative_path, source_modified_at FROM source_imports WHERE destination_volume_id=?",
        (destination_volume_id,),
    )
    for relative_path, recorded_time in rows:
        if not recorded_time:
            unavailable += 1
            continue
        destination = _safe_destination(destination_root, relative_path)
        if not destination.is_file():
            missing += 1
            continue
        try:
            modified = datetime.fromisoformat(recorded_time)
            if modified.tzinfo is None:
                modified = modified.replace(tzinfo=timezone.utc)
            os.utime(destination, (modified.timestamp(), modified.timestamp()))
            restored += 1
        except (OSError, ValueError):
            unavailable += 1
    return {"restored": restored, "missing": missing, "unavailable": unavailable}


def import_source_item(
    connection: sqlite3.Connection,
    source: ReadablePhotoSource,
    item: SourceImportItem,
    destination_root: Path,
    destination_volume_id: str,
    *,
    fsync_file: bool = True,
) -> dict[str, int | float | str]:
    """Import one source object using the existing operation/catalog model."""
    destination = _safe_destination(destination_root, item.relative_path)
    try:
        result = stream_source_to_file(source, item, destination_root, fsync_file=fsync_file)
    except Exception as exc:
        _record_failed_import(connection, source, item, destination, exc)
        raise
    return _record_successful_import(connection, source, item, destination, destination_volume_id, result)


def _record_successful_import(
    connection: sqlite3.Connection,
    source: ReadablePhotoSource,
    item: SourceImportItem,
    destination: Path,
    destination_volume_id: str,
    result: dict[str, int | float | str],
    batch_id: str | None = None,
) -> dict[str, int | float | str]:
    """Persist a completed atomic file import on the caller's SQLite thread."""
    from photovault.catalog.metadata import extract_metadata, store_metadata

    identity = source.identity()
    register_source(connection, identity)
    operation_id = "op_" + uuid.uuid4().hex
    source_path = f"android://{identity.source_id}/{item.object_id}/{item.relative_path}"
    connection.execute(
        "INSERT INTO operations(id, operation_type, created_at, status, dry_run, details_json) VALUES (?, 'IMPORT', ?, 'RUNNING', 0, ?)",
        (operation_id, utc_now(), json.dumps({"source_id": identity.source_id, "items": 1, "bytes": item.size_bytes or 0, "batch_id": batch_id}, sort_keys=True)),
    )
    cursor = connection.execute(
        "INSERT INTO operation_items(operation_id, source_path, destination_path, result) VALUES (?, ?, ?, 'RUNNING')",
        (operation_id, source_path, str(destination)),
    )
    operation_item_id = cursor.lastrowid
    connection.commit()
    actual_hash = str(result["sha256"])
    existing = connection.execute("SELECT asset_id FROM exact_hashes WHERE sha256=?", (actual_hash,)).fetchone()
    asset_id = existing[0] if existing else "asset_" + uuid.uuid4().hex
    if existing is None:
        now = utc_now()
        connection.execute("INSERT INTO assets(id, media_type, created_at, updated_at) VALUES (?, ?, ?, ?)", (asset_id, item.media_type, now, now))
        connection.execute("INSERT INTO exact_hashes(asset_id, sha256, byte_count, hashed_at) VALUES (?, ?, ?, ?)", (asset_id, actual_hash, result["bytes_written"], now))
    # Metadata is read only after the verified bytes have been atomically
    # published. This keeps the transfer safety boundary intact while making
    # EXIF/XMP-derived camera, date, dimensions, and GPS data available to the
    # catalog immediately instead of requiring a second manual scan.
    store_metadata(connection, asset_id, extract_metadata(destination))
    stat = destination.stat()
    connection.execute("INSERT INTO asset_locations(asset_id, volume_id, relative_path, filename, size_bytes, modified_ns, source_id) VALUES (?, ?, ?, ?, ?, ?, ?)", (asset_id, destination_volume_id, item.relative_path, destination.name, stat.st_size, stat.st_mtime_ns, identity.source_id))
    connection.execute("UPDATE operation_items SET asset_id=?, expected_sha256=?, result='COPIED', verification_result='VERIFIED' WHERE id=?", (asset_id, actual_hash, operation_item_id))
    connection.execute("INSERT INTO verification_history(operation_item_id, asset_id, path, expected_sha256, actual_sha256, result, verified_at) VALUES (?, ?, ?, ?, ?, 'VERIFIED', ?)", (operation_item_id, asset_id, str(destination), actual_hash, actual_hash, utc_now()))
    modified = item.modified_at.isoformat() if hasattr(item.modified_at, "isoformat") else None
    connection.execute("""INSERT INTO source_imports(source_id, logical_path, source_object_id, source_size_bytes, source_modified_at, destination_volume_id, destination_relative_path, sha256, operation_id, imported_at, batch_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, logical_path, destination_volume_id, destination_relative_path) DO UPDATE SET source_object_id=excluded.source_object_id, source_size_bytes=excluded.source_size_bytes, source_modified_at=excluded.source_modified_at, sha256=excluded.sha256, operation_id=excluded.operation_id, imported_at=excluded.imported_at, batch_id=excluded.batch_id""", (identity.source_id, item.relative_path, item.object_id, item.size_bytes, modified, destination_volume_id, item.relative_path, actual_hash, operation_id, utc_now(), batch_id))
    connection.execute("UPDATE operations SET completed_at=?, status='COMPLETED' WHERE id=?", (utc_now(), operation_id))
    connection.commit()
    return {**result, "operation_id": operation_id, "asset_id": asset_id}


def _record_failed_import(connection: sqlite3.Connection, source: ReadablePhotoSource, item: SourceImportItem, destination: Path, exc: Exception, batch_id: str | None = None) -> None:
    identity = source.identity(); register_source(connection, identity)
    operation_id = "op_" + uuid.uuid4().hex
    source_path = f"android://{identity.source_id}/{item.object_id}/{item.relative_path}"
    connection.execute("INSERT INTO operations(id, operation_type, created_at, completed_at, status, dry_run, details_json) VALUES (?, 'IMPORT', ?, ?, 'FAILED', 0, ?)", (operation_id, utc_now(), utc_now(), json.dumps({"source_id": identity.source_id, "items": 1, "bytes": item.size_bytes or 0, "batch_id": batch_id}, sort_keys=True)))
    connection.execute("INSERT INTO operation_items(operation_id, source_path, destination_path, result, verification_result, error_message) VALUES (?, ?, ?, 'FAILED', 'FAILED', ?)", (operation_id, source_path, str(destination), str(exc)))
    connection.commit()


def import_source_items(
    connection: sqlite3.Connection,
    source: ReadablePhotoSource,
    items: list[SourceImportItem],
    destination_root: Path,
    destination_volume_id: str,
    progress_callback: Callable[[dict[str, int | float | str]], None] | None = None,
    retry_callback: Callable[[SourceImportItem, int, Exception], None] | None = None,
    fsync_mode: str = "per-file",
    batch_files: int = 25,
    workers: int = 1,
    cancel_callback: Callable[[], bool] | None = None,
    retry_attempts: int = 0,
    retry_base_delay_seconds: float = 0.25,
) -> dict[str, object]:
    """Import only NEW items from a reviewed plan; source remains read-only.

    Batch mode never exposes a partial filename. A crash can leave the most
    recent batch not durably flushed, so resuming must reverify those files.
    """
    if fsync_mode not in {"per-file", "batch"}:
        raise ValueError("fsync_mode must be 'per-file' or 'batch'")
    if batch_files < 1:
        raise ValueError("batch_files must be positive")
    if workers < 1:
        raise ValueError("workers must be positive")
    if retry_attempts < 0 or retry_base_delay_seconds < 0:
        raise ValueError("retry settings cannot be negative")
    if cancel_callback is not None and cancel_callback():
        raise ImportCancelled("import cancelled before planning")
    decisions = plan_source_import(connection, source, items, destination_root, destination_volume_id)
    if any(decision.status == SourceImportStatus.CONFLICT for decision in decisions):
        raise FileExistsError("import plan contains destination conflicts")
    imported: list[dict[str, object]] = []
    already_imported = 0
    pending_durability: list[Path] = []

    def flush_batch() -> None:
        if not pending_durability:
            return
        directories: set[Path] = set()
        for path in pending_durability:
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            directories.add(path.parent)
        for directory in directories:
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        pending_durability.clear()

    new_decisions = []
    for decision in decisions:
        if decision.status == SourceImportStatus.ALREADY_IMPORTED:
            already_imported += 1
            continue
        new_decisions.append(decision)

    identity = source.identity()
    batch_id = start_import_batch(
        connection,
        source_id=identity.source_id,
        destination_volume_id=destination_volume_id,
        planned_items=len(decisions),
        planned_bytes=sum(decision.item.size_bytes or 0 for decision in decisions),
        details={"fsync_mode": fsync_mode, "batch_files": batch_files, "workers": workers},
    )

    def finish_batch(status: str, *, failed_items: int = 0, details: dict[str, object] | None = None) -> None:
        finish_import_batch(
            connection,
            batch_id,
            status=status,
            imported_items=len(imported),
            already_imported_items=already_imported,
            failed_items=failed_items,
            imported_bytes=sum(int(row.get("bytes_written", 0)) for row in imported),
            details=details,
        )

    def accept_result(decision: SourceImportDecision, result: dict[str, int | float | str]) -> None:
        result = _record_successful_import(connection, source, decision.item, _safe_destination(destination_root, decision.item.relative_path), destination_volume_id, result, batch_id)
        imported.append(result)
        if fsync_mode == "batch":
            pending_durability.append(Path(str(result["destination"])))
            if len(pending_durability) >= batch_files:
                flush_batch()
        if progress_callback is not None:
            progress_callback(result)

    def stream_with_retry(decision: SourceImportDecision) -> dict[str, int | float | str]:
        """Retry only transport-like failures; retained partials make retries safe."""
        attempt = 0
        while True:
            try:
                return stream_source_to_file(
                    source, decision.item, destination_root,
                    fsync_file=fsync_mode == "per-file", cancel_callback=cancel_callback,
                )
            except ImportCancelled:
                raise
            except (ValueError, FileExistsError, PermissionError):
                raise
            except Exception as exc:
                if attempt >= retry_attempts:
                    raise
                attempt += 1
                if retry_callback is not None:
                    retry_callback(decision.item, attempt, exc)
                if retry_base_delay_seconds:
                    time.sleep(retry_base_delay_seconds * (2 ** (attempt - 1)))

    if workers == 1:
        for decision in new_decisions:
            try:
                result = stream_with_retry(decision)
            except ImportCancelled:
                finish_batch("CANCELLED")
                raise
            except Exception as exc:
                _record_failed_import(connection, source, decision.item, _safe_destination(destination_root, decision.item.relative_path), exc, batch_id)
                finish_batch("FAILED", failed_items=1, details={"error": str(exc)})
                raise
            accept_result(decision, result)
    else:
        failures: list[Exception] = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="photovault-copy") as executor:
            futures = {
                executor.submit(
                    stream_with_retry, decision,
                ): decision
                for decision in new_decisions
            }
            for future in as_completed(futures):
                decision = futures[future]
                try:
                    accept_result(decision, future.result())
                except ImportCancelled as exc:
                    failures.append(exc)
                except Exception as exc:
                    _record_failed_import(connection, source, decision.item, _safe_destination(destination_root, decision.item.relative_path), exc, batch_id)
                    failures.append(exc)
        if failures:
            cancelled = next((failure for failure in failures if isinstance(failure, ImportCancelled)), None)
            if cancelled is not None:
                finish_batch("CANCELLED", failed_items=len(failures), details={"error": str(cancelled)})
                raise cancelled
            finish_batch("FAILED", failed_items=len(failures), details={"error": str(failures[0])})
            raise failures[0]
    flush_batch()
    restore_import_modified_times(connection, destination_root, destination_volume_id)
    finish_batch("COMPLETED")
    return {
        "batch_id": batch_id,
        "planned": len(decisions),
        "imported": len(imported),
        "already_imported": already_imported,
        "results": imported,
    }
