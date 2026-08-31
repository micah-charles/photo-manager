"""Catalog-only favourites; these annotations never modify original media."""
from __future__ import annotations

import sqlite3

from .scanner import utc_now


def set_favourite(connection: sqlite3.Connection, asset_id: str, note: str = "") -> None:
    if connection.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone() is None:
        raise ValueError(f"unknown asset: {asset_id}")
    now = utc_now()
    connection.execute(
        """INSERT INTO asset_favourites(asset_id, note, created_at, updated_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(asset_id) DO UPDATE SET note=excluded.note, updated_at=excluded.updated_at""",
        (asset_id, note.strip(), now, now),
    )
    connection.commit()


def remove_favourite(connection: sqlite3.Connection, asset_id: str) -> bool:
    cursor = connection.execute("DELETE FROM asset_favourites WHERE asset_id=?", (asset_id,))
    connection.commit()
    return cursor.rowcount > 0


def list_favourites(connection: sqlite3.Connection, limit: int = 500) -> list[sqlite3.Row]:
    return list(connection.execute(
        """SELECT f.asset_id, f.note, f.updated_at, al.filename, al.relative_path, al.volume_id,
                  COALESCE(mm.capture_datetime, al.capture_date) AS captured, th.path AS thumbnail_path
           FROM asset_favourites f
           JOIN asset_locations al ON al.asset_id=f.asset_id AND al.missing_since IS NULL
           LEFT JOIN media_metadata mm ON mm.asset_id=f.asset_id
           LEFT JOIN thumbnails th ON th.asset_id=f.asset_id AND th.version='v1-320'
           ORDER BY f.updated_at DESC, al.relative_path LIMIT ?""",
        (max(1, limit),),
    ))
