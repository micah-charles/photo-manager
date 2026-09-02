from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import sqlite3

from .hashing import sha256_file
from .metadata import extract_metadata, store_metadata
from .thumbnails import generate_thumbnail
from photovault.observability import log_event
from photovault.platform.base import VolumeProvider
from photovault.platform.provider import default_volume_provider
from photovault.catalog.sources import register_source
from photovault.sources.base import SourceIdentity


MEDIA_EXTENSIONS = {
    ".jpg": "IMAGE", ".jpeg": "IMAGE", ".png": "IMAGE", ".gif": "IMAGE", ".heic": "IMAGE",
    ".heif": "IMAGE", ".tif": "IMAGE", ".tiff": "IMAGE", ".webp": "IMAGE",
    ".cr2": "IMAGE", ".cr3": "IMAGE", ".nef": "IMAGE", ".arw": "IMAGE",
    ".dng": "IMAGE", ".raf": "IMAGE", ".orf": "IMAGE", ".rw2": "IMAGE",
    ".mov": "VIDEO", ".mp4": "VIDEO", ".m4v": "VIDEO", ".avi": "VIDEO",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def volume_id_for(identity_value: str) -> str:
    return "vol_" + hashlib.sha256(identity_value.encode()).hexdigest()[:24]


def iter_media(root: Path) -> Iterable[tuple[Path, str]]:
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        media_type = MEDIA_EXTENSIONS.get(path.suffix.lower())
        if media_type:
            yield path, media_type


def attach_exact_hash(connection: sqlite3.Connection, asset_id: str, digest: str, size_bytes: int) -> str:
    """Attach a hash and return the canonical asset for that exact content."""
    now = utc_now()
    current = connection.execute(
        "SELECT asset_id FROM exact_hashes WHERE sha256=?", (digest,)
    ).fetchone()
    if current is None:
        previous = connection.execute(
            "SELECT sha256 FROM exact_hashes WHERE asset_id=?", (asset_id,)
        ).fetchone()
        if previous is not None and previous[0] != digest:
            connection.execute("DELETE FROM exact_hashes WHERE asset_id=?", (asset_id,))
        connection.execute(
            "INSERT INTO exact_hashes(asset_id, sha256, byte_count, hashed_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(asset_id) DO UPDATE SET sha256=excluded.sha256, byte_count=excluded.byte_count, hashed_at=excluded.hashed_at",
            (asset_id, digest, size_bytes, now),
        )
        return asset_id

    canonical_id = current[0]
    if canonical_id == asset_id:
        connection.execute(
            "UPDATE exact_hashes SET byte_count=?, hashed_at=? WHERE asset_id=?",
            (size_bytes, now, asset_id),
        )
        return asset_id

    connection.execute("UPDATE asset_locations SET asset_id=? WHERE asset_id=?", (canonical_id, asset_id))
    connection.execute("DELETE FROM assets WHERE id=?", (asset_id,))
    return canonical_id


def register_volume(connection: sqlite3.Connection, root: Path, provider: VolumeProvider | None = None) -> str:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"volume root is not a directory: {root}")
    provider = provider or default_volume_provider()
    identity = provider.identify(root)
    volume_id = volume_id_for(f"{identity.identity_kind}:{identity.identity_value}")
    now = utc_now()
    existing = connection.execute(
        "SELECT id FROM volumes WHERE identity_value=?",
        (identity.identity_value,),
    ).fetchone()
    if existing is None:
        # Upgrade a Phase 1 path record when the same mounted root is first seen
        # with a stronger platform identity. Keep the existing ID and locations.
        existing = connection.execute(
            "SELECT id FROM volumes WHERE identity_kind IN ('phase1_path', 'path_fallback') AND current_mount_path=?",
            (str(root),),
        ).fetchone()
    if existing is not None:
        volume_id = existing[0]
    values = (
        identity.display_name, identity.identity_kind, identity.identity_value,
        identity.filesystem, identity.capacity_bytes, now, str(root), volume_id,
    )
    if existing is not None:
        connection.execute(
            "UPDATE volumes SET display_name=?, identity_kind=?, identity_value=?, filesystem=?, "
            "capacity_bytes=?, last_seen=?, current_mount_path=?, status='CONNECTED' WHERE id=?",
            values,
        )
    else:
        connection.execute(
            """
            INSERT INTO volumes(id, display_name, identity_kind, identity_value,
                                filesystem, capacity_bytes, first_seen, last_seen, current_mount_path, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'CONNECTED')
            """,
            (volume_id, identity.display_name, identity.identity_kind, identity.identity_value,
             identity.filesystem, identity.capacity_bytes, now, now, str(root)),
        )
    connection.commit()
    return volume_id


def scan_volume(
    connection: sqlite3.Connection,
    volume_id: str,
    root: Path,
    thumbnail_root: Path | None = None,
) -> dict[str, int | str]:
    root = root.expanduser().resolve()
    row = connection.execute("SELECT id FROM volumes WHERE id = ?", (volume_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown volume: {volume_id}")
    volume = connection.execute("SELECT display_name FROM volumes WHERE id=?", (volume_id,)).fetchone()
    source_id = f"folder:{volume_id}"
    register_source(connection, SourceIdentity(
        source_id=source_id,
        manufacturer="Local filesystem",
        model="Folder / removable media",
        display_name=str(volume[0] if volume else volume_id),
        adapter="local_folder",
    ))
    session_id = "scan_" + uuid.uuid4().hex
    started = utc_now()
    started_clock = time.monotonic()
    log_event("scan_started", scan_session_id=session_id, volume_id=volume_id, root=str(root))
    connection.execute(
        "INSERT INTO scan_sessions(id, volume_id, root_path, started_at, status) VALUES (?, ?, ?, ?, 'RUNNING')",
        (session_id, volume_id, str(root), started),
    )
    seen = catalogued = errors = 0
    try:
        for path, media_type in iter_media(root):
            seen += 1
            try:
                stat = path.stat()
                relative = path.relative_to(root).as_posix()
                existing = connection.execute(
                    "SELECT al.asset_id, al.size_bytes, al.modified_ns, eh.sha256, al.source_id "
                    "FROM asset_locations al LEFT JOIN exact_hashes eh ON eh.asset_id=al.asset_id "
                    "WHERE al.volume_id=? AND al.relative_path=? "
                    "ORDER BY CASE WHEN al.source_id LIKE 'folder:%' OR al.source_id IS NULL THEN 1 ELSE 0 END "
                    "LIMIT 1",
                    (volume_id, relative),
                ).fetchone()
                asset_id = existing[0] if existing else "asset_" + uuid.uuid4().hex
                obsolete_asset_id: str | None = None
                now = utc_now()
                digest = existing[3] if existing and existing[1] == stat.st_size and existing[2] == stat.st_mtime_ns else sha256_file(path)
                if existing and existing[3] and existing[3] != digest:
                    # A file replacement at the same path is a new logical asset.
                    # Keep the old asset/hash record for any other physical locations.
                    obsolete_asset_id = asset_id
                    asset_id = "asset_" + uuid.uuid4().hex
                    connection.execute(
                        "INSERT INTO assets(id, media_type, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (asset_id, media_type, now, now),
                    )
                elif existing is None:
                    connection.execute(
                        "INSERT INTO assets(id, media_type, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (asset_id, media_type, now, now),
                    )
                else:
                    connection.execute("UPDATE assets SET updated_at=? WHERE id=?", (now, asset_id))
                asset_id = attach_exact_hash(connection, asset_id, digest, stat.st_size)
                metadata = extract_metadata(path)
                store_metadata(connection, asset_id, metadata)
                if thumbnail_root is not None:
                    generate_thumbnail(connection, asset_id, path, thumbnail_root)
                connection.execute(
                    """
                    INSERT INTO asset_locations(asset_id, volume_id, relative_path, filename,
                                                size_bytes, modified_ns, capture_date, scan_session_id, source_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(volume_id, relative_path, source_id) DO UPDATE SET
                      asset_id=excluded.asset_id,
                      size_bytes=excluded.size_bytes, modified_ns=excluded.modified_ns,
                      filename=excluded.filename, capture_date=excluded.capture_date,
                      scan_session_id=excluded.scan_session_id,
                      source_id=excluded.source_id,
                      missing_since=NULL
                    """,
                    (asset_id, volume_id, relative, path.name, stat.st_size, stat.st_mtime_ns,
                     metadata.capture_datetime[:10] if metadata.capture_datetime else None, session_id,
                     existing[4] if existing and existing[4] else source_id),
                )
                if obsolete_asset_id:
                    remaining = connection.execute(
                        "SELECT COUNT(*) FROM asset_locations WHERE asset_id=?",
                        (obsolete_asset_id,),
                    ).fetchone()[0]
                    if remaining == 0:
                        connection.execute("DELETE FROM assets WHERE id=?", (obsolete_asset_id,))
                catalogued += 1
            except OSError as exc:
                errors += 1
                connection.execute(
                    "INSERT INTO scan_errors(scan_session_id, path, error_type, message, created_at) VALUES (?, ?, ?, ?, ?)",
                    (session_id, str(path), type(exc).__name__, str(exc), utc_now()),
                )
                log_event(
                    "scan_file_error",
                    scan_session_id=session_id,
                    volume_id=volume_id,
                    path=str(path),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
        connection.execute(
            "UPDATE asset_locations SET missing_since=COALESCE(missing_since, ?) "
            "WHERE volume_id=? AND (scan_session_id IS NULL OR scan_session_id<>?)",
            (utc_now(), volume_id, session_id),
        )
        connection.execute(
            "UPDATE scan_sessions SET completed_at=?, status='COMPLETED', files_seen=?, files_catalogued=?, errors=? WHERE id=?",
            (utc_now(), seen, catalogued, errors, session_id),
        )
        connection.execute("UPDATE volumes SET last_seen=?, status='CONNECTED' WHERE id=?", (utc_now(), volume_id))
        connection.commit()
        log_event(
            "scan_completed",
            scan_session_id=session_id,
            volume_id=volume_id,
            files_seen=seen,
            files_catalogued=catalogued,
            errors=errors,
            duration_ms=round((time.monotonic() - started_clock) * 1000),
        )
    except Exception:
        connection.execute("UPDATE scan_sessions SET completed_at=?, status='FAILED' WHERE id=?", (utc_now(), session_id))
        connection.commit()
        log_event(
            "scan_failed",
            scan_session_id=session_id,
            volume_id=volume_id,
            files_seen=seen,
            files_catalogued=catalogued,
            errors=errors,
            duration_ms=round((time.monotonic() - started_clock) * 1000),
        )
        raise
    return {"session_id": session_id, "files_seen": seen, "files_catalogued": catalogued, "errors": errors}
