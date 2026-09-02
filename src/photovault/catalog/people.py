from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import sqlite3
import uuid
from datetime import datetime, timezone


@dataclass(frozen=True)
class FaceObservation:
    """Platform-neutral face result; coordinates are normalized 0..1."""
    left: float
    top: float
    right: float
    bottom: float
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True)
class Person:
    id: str
    display_name: str
    engine: str
    item_count: int


def list_people(connection: sqlite3.Connection) -> list[Person]:
    return [Person(str(row[0]), str(row[1] or ""), str(row[2]), int(row[3])) for row in connection.execute(
        """SELECT p.id, p.display_name, p.engine, COUNT(pm.asset_id)
           FROM people p LEFT JOIN person_members pm ON pm.person_id=p.id
           GROUP BY p.id ORDER BY lower(COALESCE(p.display_name, p.external_key)), p.id"""
    )]


def create_person(connection: sqlite3.Connection, name: str) -> str:
    clean = " ".join(name.strip().split())
    if not clean:
        raise ValueError("person name is required")
    person_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection.execute(
        "INSERT INTO people(id, engine, external_key, display_name, created_at, updated_at) VALUES (?, 'manual', ?, ?, ?, ?)",
        (person_id, f"manual:{person_id}", clean, now, now),
    )
    connection.commit()
    return person_id


def rename_person(connection: sqlite3.Connection, person_id: str, name: str) -> None:
    clean = " ".join(name.strip().split())
    if not clean:
        raise ValueError("person name is required")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changed = connection.execute("UPDATE people SET display_name=?, updated_at=? WHERE id=?", (clean, now, person_id)).rowcount
    if not changed:
        raise ValueError("unknown person")
    connection.commit()


def delete_person(connection: sqlite3.Connection, person_id: str) -> None:
    changed = connection.execute("DELETE FROM people WHERE id=?", (person_id,)).rowcount
    if not changed:
        raise ValueError("unknown person")
    connection.commit()


def assign_person(connection: sqlite3.Connection, asset_ids: list[str] | tuple[str, ...], person_id: str) -> int:
    if connection.execute("SELECT 1 FROM people WHERE id=?", (person_id,)).fetchone() is None:
        raise ValueError("unknown person")
    changed = 0
    for asset_id in dict.fromkeys(str(item) for item in asset_ids):
        if connection.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone() is None:
            continue
        cursor = connection.execute(
            "INSERT OR IGNORE INTO person_members(person_id, asset_id, face_count) VALUES (?, ?, 1)",
            (person_id, asset_id),
        )
        changed += cursor.rowcount
    connection.commit()
    return changed


def remove_person(connection: sqlite3.Connection, asset_ids: list[str] | tuple[str, ...], person_id: str) -> int:
    cursor = connection.executemany(
        "DELETE FROM person_members WHERE person_id=? AND asset_id=?",
        ((person_id, str(asset_id)) for asset_id in dict.fromkeys(asset_ids)),
    )
    connection.commit()
    return max(0, int(cursor.rowcount))


class FaceEngine(Protocol):
    def detect(self, path: Path) -> list[FaceObservation]: ...


class UnavailableFaceEngine:
    """Explicit no-op until a macOS Vision or ONNX engine is installed."""
    def detect(self, path: Path) -> list[FaceObservation]:
        return []
