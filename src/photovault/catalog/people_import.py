"""Import read-only macOS Vision face-group results into the catalog."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class PeopleImportReport:
    people: int
    matched_assets: int
    unmatched_paths: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def import_macos_vision_features(connection: sqlite3.Connection, payload: dict[str, object]) -> PeopleImportReport:
    """Store a Vision result without touching originals or retaining face embeddings.

    The legacy Vision extractor identifies a person only within its own run, so
    each import replaces the previous `macos_vision` membership view.  The user
    may rename the generated clusters afterwards; a future stable embedding
    engine can coexist under a different engine name.
    """
    images = payload.get("images")
    if not isinstance(images, list):
        raise ValueError("Vision feature JSON must contain an images list")
    locations: dict[str, str] = {}
    for asset_id, mount, relative_path in connection.execute(
        """SELECT al.asset_id, v.current_mount_path, al.relative_path
           FROM asset_locations al JOIN volumes v ON v.id=al.volume_id
           WHERE al.missing_since IS NULL AND v.current_mount_path IS NOT NULL"""
    ):
        locations[str((Path(str(mount)) / str(relative_path)).resolve())] = str(asset_id)
    memberships: dict[str, dict[str, int]] = {}
    unmatched = 0
    for item in images:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str):
            continue
        asset_id = locations.get(str(Path(path).expanduser().resolve()))
        if asset_id is None:
            unmatched += 1; continue
        try:
            face_count = max(1, int(item.get("face_count") or 1))
        except (TypeError, ValueError):
            face_count = 1
        ids = item.get("person_ids")
        if not isinstance(ids, list):
            continue
        for external_key in ids:
            key = str(external_key)
            memberships.setdefault(key, {})[asset_id] = face_count
    now = _now()
    connection.execute("DELETE FROM people WHERE engine='macos_vision'")
    for key, members in memberships.items():
        person_id = "person_" + uuid.uuid4().hex
        connection.execute(
            "INSERT INTO people(id, engine, external_key, display_name, created_at, updated_at) VALUES (?, 'macos_vision', ?, ?, ?, ?)",
            (person_id, key, f"Person {key}", now, now),
        )
        connection.executemany(
            "INSERT INTO person_members(person_id, asset_id, face_count) VALUES (?, ?, ?)",
            ((person_id, asset_id, face_count) for asset_id, face_count in members.items()),
        )
    connection.commit()
    return PeopleImportReport(len(memberships), sum(len(items) for items in memberships.values()), unmatched)


def import_macos_vision_features_file(connection: sqlite3.Connection, path: Path) -> PeopleImportReport:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read Vision feature JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Vision feature JSON root must be an object")
    return import_macos_vision_features(connection, payload)
