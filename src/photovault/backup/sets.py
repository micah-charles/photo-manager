from __future__ import annotations

import sqlite3
import uuid
from pathlib import PurePosixPath

from photovault.catalog.scanner import utc_now


def create_backup_set(connection: sqlite3.Connection, name: str, required_copies: int = 2, scope: str = "") -> str:
    if required_copies < 1:
        raise ValueError("required_copies must be at least 1")
    backup_set_id = "set_" + uuid.uuid4().hex
    now = utc_now()
    connection.execute(
        "INSERT INTO backup_sets(id, name, required_copies, scope, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (backup_set_id, name, required_copies, scope.strip("/"), now, now),
    )
    connection.commit()
    return backup_set_id


def add_member(
    connection: sqlite3.Connection,
    backup_set_id: str,
    volume_id: str,
    role: str,
    relative_root: str = "",
) -> None:
    role = role.upper()
    if role not in {"PRIMARY", "BACKUP"}:
        raise ValueError("role must be PRIMARY or BACKUP")
    if connection.execute("SELECT 1 FROM backup_sets WHERE id=?", (backup_set_id,)).fetchone() is None:
        raise ValueError(f"unknown backup set: {backup_set_id}")
    if connection.execute("SELECT 1 FROM volumes WHERE id=?", (volume_id,)).fetchone() is None:
        raise ValueError(f"unknown volume: {volume_id}")
    normalized = str(PurePosixPath(relative_root.strip("/"))) if relative_root.strip("/") else ""
    connection.execute(
        "INSERT INTO backup_set_members(backup_set_id, volume_id, role, relative_root) VALUES (?, ?, ?, ?)",
        (backup_set_id, volume_id, role, normalized),
    )
    connection.execute("UPDATE backup_sets SET updated_at=? WHERE id=?", (utc_now(), backup_set_id))
    connection.commit()
