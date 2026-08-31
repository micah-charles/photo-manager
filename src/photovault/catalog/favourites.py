"""Catalog-only favourites; these annotations never modify original media."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .scanner import utc_now


@dataclass(frozen=True)
class LegacyFavouriteImportReport:
    declared: int
    imported: int
    unmatched: int
    invalid: int


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


def import_legacy_favourites_json(connection: sqlite3.Connection, manifest_path: Path) -> LegacyFavouriteImportReport:
    """Map legacy gallery JSON paths to catalog assets without touching media.

    The legacy exporter wrote path-based browser state.  A path is accepted only
    when it maps to a currently catalogued location; unmatched entries are
    reported rather than copied, guessed or created as filesystem artefacts.
    """
    payload = json.loads(manifest_path.expanduser().read_text(encoding="utf-8"))
    rows = payload.get("favorites", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise ValueError("legacy favourites manifest must contain a favorites array")
    path_to_asset: dict[str, str] = {}
    for row in connection.execute(
        """SELECT al.asset_id, al.relative_path, v.current_mount_path
           FROM asset_locations al JOIN volumes v ON v.id=al.volume_id
           WHERE al.missing_since IS NULL AND v.current_mount_path IS NOT NULL"""
    ):
        path_to_asset[str((Path(row[2]) / row[1]).resolve())] = str(row[0])
    imported = unmatched = invalid = 0
    for entry in rows:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            invalid += 1
            continue
        asset_id = path_to_asset.get(str(Path(entry["path"]).expanduser().resolve()))
        if asset_id is None:
            unmatched += 1
            continue
        note_parts = ["Imported legacy gallery favourite"]
        if entry.get("location_label"):
            note_parts.append(f"location={entry['location_label']}")
        people = entry.get("person_labels")
        if isinstance(people, list) and people:
            note_parts.append("people=" + ", ".join(str(person) for person in people))
        now = utc_now()
        connection.execute(
            """INSERT INTO asset_favourites(asset_id, note, created_at, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(asset_id) DO UPDATE SET note=excluded.note, updated_at=excluded.updated_at""",
            (asset_id, "; ".join(note_parts), now, now),
        )
        imported += 1
    connection.commit()
    return LegacyFavouriteImportReport(len(rows), imported, unmatched, invalid)
