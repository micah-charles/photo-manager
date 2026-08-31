"""Persistent, non-destructive Android Companion backup profile history."""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable

from photovault.catalog.scanner import utc_now


def upsert_android_backup_profile(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    name: str,
    folder_path: str = "",
    folder_paths: Iterable[str] | None = None,
    media_filter: str,
    destination_volume_id: str,
    destination_relative_root: str = "",
    workers: int = 5,
    fsync_mode: str = "batch",
    batch_files: int = 25,
) -> str:
    """Create/update a profile keyed by stable source and destination identity.

    ``folder_path`` remains accepted for existing single-folder callers. New
    callers pass ``folder_paths``; the canonical joined value is retained in
    the older column solely as the profile's stable selection key, while the
    normalized child table preserves individual folders for UI and reporting.
    """
    selected_folders = tuple(sorted({path.strip("/") for path in (folder_paths or (folder_path,)) if path.strip("/")}))
    folder_path = "|".join(selected_folders)
    destination_relative_root = destination_relative_root.strip("/")
    if not folder_path:
        raise ValueError("folder_path is required")
    if media_filter not in {"ALL", "IMAGE", "VIDEO"}:
        raise ValueError("media_filter must be ALL, IMAGE or VIDEO")
    if not 1 <= workers <= 8:
        raise ValueError("workers must be between 1 and 8")
    if fsync_mode not in {"per-file", "batch"} or batch_files < 1:
        raise ValueError("invalid durability settings")
    now = utc_now()
    existing = connection.execute(
        """SELECT id FROM android_backup_profiles WHERE source_id=? AND folder_path=?
           AND media_filter=? AND destination_volume_id=? AND destination_relative_root=?""",
        (source_id, folder_path, media_filter, destination_volume_id, destination_relative_root),
    ).fetchone()
    if existing is not None:
        profile_id = str(existing[0])
        connection.execute(
            """UPDATE android_backup_profiles SET name=?, workers=?, fsync_mode=?, batch_files=?, updated_at=?
               WHERE id=?""",
            (name.strip() or folder_path, workers, fsync_mode, batch_files, now, profile_id),
        )
    else:
        profile_id = "android_profile_" + uuid.uuid4().hex
        connection.execute(
            """INSERT INTO android_backup_profiles(
                id, source_id, name, folder_path, media_filter, destination_volume_id,
                destination_relative_root, workers, fsync_mode, batch_files, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (profile_id, source_id, name.strip() or folder_path, folder_path, media_filter,
             destination_volume_id, destination_relative_root, workers, fsync_mode,
             batch_files, now, now),
        )
    connection.execute("DELETE FROM android_backup_profile_folders WHERE profile_id=?", (profile_id,))
    connection.executemany(
        "INSERT INTO android_backup_profile_folders(profile_id, folder_path) VALUES (?, ?)",
        [(profile_id, folder) for folder in selected_folders],
    )
    connection.commit()
    return profile_id


def start_android_backup_snapshot(
    connection: sqlite3.Connection,
    profile_id: str,
    *,
    planned_items: int,
    planned_bytes: int,
) -> str:
    snapshot_id = "android_snapshot_" + uuid.uuid4().hex
    connection.execute(
        """INSERT INTO android_backup_snapshots(
            id, profile_id, started_at, status, planned_items, planned_bytes
        ) VALUES (?, ?, ?, 'RUNNING', ?, ?)""",
        (snapshot_id, profile_id, utc_now(), planned_items, planned_bytes),
    )
    connection.commit()
    return snapshot_id


def finish_android_backup_snapshot(
    connection: sqlite3.Connection,
    snapshot_id: str,
    *,
    status: str,
    imported_items: int = 0,
    already_imported_items: int = 0,
    failed_items: int = 0,
    imported_bytes: int = 0,
    details: dict[str, object] | None = None,
) -> None:
    if status not in {"COMPLETED", "CANCELLED", "FAILED"}:
        raise ValueError("invalid snapshot status")
    connection.execute(
        """UPDATE android_backup_snapshots SET completed_at=?, status=?, imported_items=?,
           already_imported_items=?, failed_items=?, imported_bytes=?, details_json=? WHERE id=?""",
        (utc_now(), status, imported_items, already_imported_items, failed_items,
         imported_bytes, json.dumps(details or {}, sort_keys=True), snapshot_id),
    )
    if status == "COMPLETED":
        connection.execute(
            """UPDATE android_backup_profiles SET last_completed_at=?, updated_at=?
               WHERE id=(SELECT profile_id FROM android_backup_snapshots WHERE id=?)""",
            (utc_now(), utc_now(), snapshot_id),
        )
    connection.commit()


def list_android_backup_profiles(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(connection.execute(
        """SELECT p.*, v.display_name AS destination_volume_name, v.status AS destination_status
           FROM android_backup_profiles p JOIN volumes v ON v.id=p.destination_volume_id
           ORDER BY p.updated_at DESC, p.name"""
    ))


def profile_folders(connection: sqlite3.Connection, profile_id: str) -> tuple[str, ...]:
    """Return normalized selected folders, with a migration-safe legacy fallback."""
    folders = tuple(str(row[0]) for row in connection.execute(
        "SELECT folder_path FROM android_backup_profile_folders WHERE profile_id=? ORDER BY folder_path", (profile_id,)
    ))
    if folders:
        return folders
    row = connection.execute("SELECT folder_path FROM android_backup_profiles WHERE id=?", (profile_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown Android backup profile: {profile_id}")
    return tuple(part for part in str(row[0]).split("|") if part)


def missing_from_source(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    destination_volume_id: str,
    folders: Iterable[str],
    current_logical_paths: Iterable[str],
) -> tuple[str, ...]:
    """Report prior verified imports absent from a selected source inventory.

    This is intentionally informational. Callers must never turn this result
    into a destination delete operation.
    """
    normalized = tuple(sorted({folder.strip("/") for folder in folders if folder.strip("/")}))
    if not normalized:
        return ()
    conditions = " OR ".join("logical_path LIKE ?" for _ in normalized)
    params: list[object] = [source_id, destination_volume_id]
    params.extend(folder + "/%" for folder in normalized)
    previous = {
        str(row[0]) for row in connection.execute(
            f"""SELECT DISTINCT logical_path FROM source_imports
                WHERE source_id=? AND destination_volume_id=? AND ({conditions})""",
            params,
        )
    }
    return tuple(sorted(previous - set(current_logical_paths)))
