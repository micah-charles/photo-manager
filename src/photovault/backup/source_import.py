from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO
import sqlite3
import uuid
from datetime import datetime

from photovault.catalog.sources import register_source
from photovault.catalog.scanner import utc_now
from photovault.sources.base import ReadablePhotoSource


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
            SELECT source_size_bytes, source_modified_at
            FROM source_imports
            WHERE source_id=? AND logical_path=? AND destination_volume_id=?
            ORDER BY imported_at DESC LIMIT 1
            """,
            (identity.source_id, item.relative_path, destination_volume_id),
        ).fetchone()
        modified = item.modified_at.isoformat() if hasattr(item.modified_at, "isoformat") else None
        if existing and destination.exists() and existing[0] == item.size_bytes and existing[1] == modified:
            decisions.append(SourceImportDecision(item, SourceImportStatus.ALREADY_IMPORTED, "matching completed import exists"))
        elif destination.exists():
            decisions.append(SourceImportDecision(item, SourceImportStatus.CONFLICT, "destination exists but is not a matching completed import"))
        else:
            decisions.append(SourceImportDecision(item, SourceImportStatus.NEW, "no matching completed import exists"))
    return decisions


def stream_source_to_file(
    source: ReadablePhotoSource,
    item: SourceImportItem,
    destination_root: Path,
) -> dict[str, int | float | str]:
    """Stream one source object through bounded memory into an atomic destination."""
    destination = _safe_destination(destination_root, item.relative_path)
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".photomanager-partial")
    if partial.exists():
        raise FileExistsError(f"stale partial destination exists: {partial}")

    digest = hashlib.sha256()
    bytes_written = 0
    started = time.monotonic()
    try:
        with partial.open("xb") as output:
            class HashingSink:
                def write(self, data: bytes) -> int:
                    nonlocal bytes_written
                    digest.update(data)
                    bytes_written += len(data)
                    return output.write(data)

            metrics = source.stream_object(item.object_id, HashingSink())
            output.flush()
            os.fsync(output.fileno())
        actual_hash = digest.hexdigest()
        if item.size_bytes is not None and bytes_written != item.size_bytes:
            raise ValueError(f"source size mismatch: expected {item.size_bytes}, got {bytes_written}")
        if item.expected_sha256 is not None and actual_hash != item.expected_sha256:
            raise ValueError(f"source SHA-256 mismatch: expected {item.expected_sha256}, got {actual_hash}")
        if destination.exists():
            raise FileExistsError(f"destination appeared during import: {destination}")
        os.replace(partial, destination)
        return {
            "object_id": item.object_id,
            "destination": str(destination),
            "bytes_written": bytes_written,
            "sha256": actual_hash,
            "elapsed_seconds": time.monotonic() - started,
            "source_bytes_per_second": metrics.get("bytes_per_second", 0.0),
        }
    except Exception:
        if partial.exists():
            partial.unlink()
        raise


def import_source_item(
    connection: sqlite3.Connection,
    source: ReadablePhotoSource,
    item: SourceImportItem,
    destination_root: Path,
    destination_volume_id: str,
) -> dict[str, int | float | str]:
    """Import one source object using the existing operation/catalog model."""
    identity = source.identity()
    register_source(connection, identity)
    destination = _safe_destination(destination_root, item.relative_path)
    operation_id = "op_" + uuid.uuid4().hex
    source_path = f"android://{identity.source_id}/{item.object_id}/{item.relative_path}"
    connection.execute(
        "INSERT INTO operations(id, operation_type, created_at, status, dry_run, details_json) VALUES (?, 'IMPORT', ?, 'RUNNING', 0, ?)",
        (operation_id, utc_now(), json.dumps({"source_id": identity.source_id, "items": 1, "bytes": item.size_bytes or 0}, sort_keys=True)),
    )
    cursor = connection.execute(
        "INSERT INTO operation_items(operation_id, source_path, destination_path, result) VALUES (?, ?, ?, 'RUNNING')",
        (operation_id, source_path, str(destination)),
    )
    operation_item_id = cursor.lastrowid
    connection.commit()
    try:
        result = stream_source_to_file(source, item, destination_root)
        actual_hash = str(result["sha256"])
        existing = connection.execute("SELECT asset_id FROM exact_hashes WHERE sha256=?", (actual_hash,)).fetchone()
        asset_id = existing[0] if existing else "asset_" + uuid.uuid4().hex
        if existing is None:
            now = utc_now()
            connection.execute(
                "INSERT INTO assets(id, media_type, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (asset_id, item.media_type, now, now),
            )
            connection.execute(
                "INSERT INTO exact_hashes(asset_id, sha256, byte_count, hashed_at) VALUES (?, ?, ?, ?)",
                (asset_id, actual_hash, result["bytes_written"], now),
            )
        stat = destination.stat()
        connection.execute(
            """
            INSERT INTO asset_locations(asset_id, volume_id, relative_path, filename, size_bytes, modified_ns)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (asset_id, destination_volume_id, item.relative_path, destination.name, stat.st_size, stat.st_mtime_ns),
        )
        connection.execute(
            "UPDATE operation_items SET asset_id=?, expected_sha256=?, result='COPIED', verification_result='VERIFIED' WHERE id=?",
            (asset_id, actual_hash, operation_item_id),
        )
        connection.execute(
            "INSERT INTO verification_history(operation_item_id, asset_id, path, expected_sha256, actual_sha256, result, verified_at) VALUES (?, ?, ?, ?, ?, 'VERIFIED', ?)",
            (operation_item_id, asset_id, str(destination), actual_hash, actual_hash, utc_now()),
        )
        modified = item.modified_at.isoformat() if hasattr(item.modified_at, "isoformat") else None
        connection.execute(
            """
            INSERT INTO source_imports(
                source_id, logical_path, source_object_id, source_size_bytes,
                source_modified_at, destination_volume_id, destination_relative_path,
                sha256, operation_id, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, logical_path, destination_volume_id, destination_relative_path)
            DO UPDATE SET source_object_id=excluded.source_object_id,
                source_size_bytes=excluded.source_size_bytes,
                source_modified_at=excluded.source_modified_at,
                sha256=excluded.sha256, operation_id=excluded.operation_id,
                imported_at=excluded.imported_at
            """,
            (identity.source_id, item.relative_path, item.object_id, item.size_bytes,
             modified, destination_volume_id, item.relative_path, actual_hash,
             operation_id, utc_now()),
        )
        connection.execute("UPDATE operations SET completed_at=?, status='COMPLETED' WHERE id=?", (utc_now(), operation_id))
        connection.commit()
        return {**result, "operation_id": operation_id, "asset_id": asset_id}
    except Exception as exc:
        connection.execute(
            "UPDATE operation_items SET result='FAILED', verification_result='FAILED', error_message=? WHERE id=?",
            (str(exc), operation_item_id),
        )
        connection.execute("UPDATE operations SET completed_at=?, status='FAILED' WHERE id=?", (utc_now(), operation_id))
        connection.commit()
        raise


def import_source_items(
    connection: sqlite3.Connection,
    source: ReadablePhotoSource,
    items: list[SourceImportItem],
    destination_root: Path,
    destination_volume_id: str,
) -> dict[str, object]:
    """Import only NEW items from a reviewed plan; source remains read-only."""
    decisions = plan_source_import(connection, source, items, destination_root, destination_volume_id)
    if any(decision.status == SourceImportStatus.CONFLICT for decision in decisions):
        raise FileExistsError("import plan contains destination conflicts")
    imported: list[dict[str, object]] = []
    already_imported = 0
    for decision in decisions:
        if decision.status == SourceImportStatus.ALREADY_IMPORTED:
            already_imported += 1
            continue
        imported.append(import_source_item(connection, source, decision.item, destination_root, destination_volume_id))
    return {
        "planned": len(decisions),
        "imported": len(imported),
        "already_imported": already_imported,
        "results": imported,
    }
