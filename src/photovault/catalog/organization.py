"""User-owned library organisation metadata.

These helpers only update the catalog. They never move, rename, rewrite, or
delete a media file; physical backup operations remain in ``photovault.backup``.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_tag(name: str) -> str:
    clean = " ".join(name.strip().split())
    if not clean:
        raise ValueError("tag name is required")
    return clean.casefold()


@dataclass(frozen=True)
class Event:
    id: str
    name: str
    start_datetime: str | None
    end_datetime: str | None
    event_type: str
    description: str
    item_count: int
    is_suggested: bool
    default_place_id: str | None = None


@dataclass(frozen=True)
class Tag:
    id: str
    name: str
    item_count: int


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    country: str | None
    region: str | None
    city: str | None
    item_count: int


def set_asset_source(connection: sqlite3.Connection, asset_id: str, source_id: str) -> None:
    """Attach source provenance to a catalogued physical location."""
    exists = connection.execute("SELECT 1 FROM source_profiles WHERE source_id=?", (source_id,)).fetchone()
    if exists is None:
        raise ValueError("unknown source")
    changed = connection.execute(
        "UPDATE asset_locations SET source_id=? WHERE asset_id=? AND missing_since IS NULL",
        (source_id, asset_id),
    ).rowcount
    if not changed:
        raise ValueError("unknown asset")
    connection.commit()


def list_sources(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(connection.execute(
        """SELECT sp.source_id, sp.display_name, sp.source_type, sp.manufacturer,
                  sp.model, sp.time_offset_seconds, sp.last_seen,
                  COUNT(DISTINCT al.asset_id) AS item_count
           FROM source_profiles sp LEFT JOIN asset_locations al
             ON al.source_id=sp.source_id AND al.missing_since IS NULL
           GROUP BY sp.source_id ORDER BY sp.display_name"""
    ))


def set_source_time_offset(connection: sqlite3.Connection, source_id: str, offset_seconds: int) -> None:
    """Set a display-only capture-time offset for one source."""
    changed = connection.execute(
        "UPDATE source_profiles SET time_offset_seconds=?, last_seen=last_seen WHERE source_id=?",
        (int(offset_seconds), source_id),
    ).rowcount
    if not changed:
        raise ValueError("unknown source")
    connection.commit()


def create_event(
    connection: sqlite3.Connection,
    name: str,
    *,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    event_type: str = "other",
    description: str = "",
    default_place_id: str | None = None,
    is_suggested: bool = False,
) -> str:
    clean = " ".join(name.strip().split())
    if not clean:
        raise ValueError("event name is required")
    if start_datetime and end_datetime and start_datetime > end_datetime:
        raise ValueError("event start must not be after event end")
    if default_place_id and connection.execute("SELECT 1 FROM places WHERE id=?", (default_place_id,)).fetchone() is None:
        raise ValueError("unknown default place")
    event_id = str(uuid.uuid4())
    now = _now()
    connection.execute(
        """INSERT INTO events(id, name, start_datetime, end_datetime, event_type,
           description, default_place_id, is_suggested, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, clean, start_datetime, end_datetime, event_type, description,
         default_place_id, int(is_suggested), now, now),
    )
    connection.commit()
    return event_id


def add_event_assets_in_date_range(
    connection: sqlite3.Connection,
    event_id: str,
    start_date: str,
    end_date: str,
    *,
    membership_source: str = "date_range",
) -> int:
    """Add all currently catalogued assets captured between two inclusive dates."""
    if connection.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone() is None:
        raise ValueError("unknown event")
    if not start_date or not end_date or start_date > end_date:
        raise ValueError("event date range is invalid")
    rows = connection.execute(
        """SELECT al.asset_id
           FROM asset_locations al
           LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
           WHERE al.missing_since IS NULL
             AND substr(COALESCE(mm.capture_datetime, al.capture_date), 1, 10) BETWEEN ? AND ?
           ORDER BY COALESCE(mm.capture_datetime, al.capture_date), al.asset_id""",
        (start_date, end_date),
    ).fetchall()
    return add_assets_to_event(connection, event_id, [str(row[0]) for row in rows], membership_source=membership_source)


def add_assets_to_event(
    connection: sqlite3.Connection,
    event_id: str,
    asset_ids: list[str] | tuple[str, ...],
    *,
    membership_source: str = "manual",
) -> int:
    if connection.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone() is None:
        raise ValueError("unknown event")
    now = _now()
    cursor = connection.executemany(
        """INSERT OR IGNORE INTO event_assets(event_id, asset_id, membership_source, created_at)
           SELECT ?, id, ?, ? FROM assets WHERE id=?""",
        ((event_id, membership_source, now, str(asset_id)) for asset_id in dict.fromkeys(asset_ids)),
    )
    connection.execute("UPDATE events SET updated_at=? WHERE id=?", (now, event_id))
    connection.commit()
    return max(0, int(cursor.rowcount))


def update_event(connection: sqlite3.Connection, event_id: str, *, name: str, start_datetime: str | None = None, end_datetime: str | None = None, event_type: str = "other", description: str = "", default_place_id: str | None = None) -> None:
    clean = " ".join(name.strip().split())
    if not clean:
        raise ValueError("event name is required")
    if start_datetime and end_datetime and start_datetime > end_datetime:
        raise ValueError("event start must not be after event end")
    if default_place_id and connection.execute("SELECT 1 FROM places WHERE id=?", (default_place_id,)).fetchone() is None:
        raise ValueError("unknown default place")
    changed = connection.execute(
        "UPDATE events SET name=?, start_datetime=?, end_datetime=?, event_type=?, description=?, default_place_id=?, updated_at=? WHERE id=?",
        (clean, start_datetime, end_datetime, event_type, description, default_place_id, _now(), event_id),
    ).rowcount
    if not changed:
        raise ValueError("unknown event")
    connection.commit()


def delete_event(connection: sqlite3.Connection, event_id: str) -> None:
    connection.execute("DELETE FROM event_assets WHERE event_id=?", (event_id,))
    changed = connection.execute("DELETE FROM events WHERE id=?", (event_id,)).rowcount
    if not changed:
        raise ValueError("unknown event")
    connection.commit()


def remove_assets_from_event(connection: sqlite3.Connection, event_id: str, asset_ids: list[str] | tuple[str, ...]) -> int:
    cursor = connection.executemany(
        "DELETE FROM event_assets WHERE event_id=? AND asset_id=?",
        ((event_id, str(asset_id)) for asset_id in dict.fromkeys(asset_ids)),
    )
    connection.execute("UPDATE events SET updated_at=? WHERE id=?", (_now(), event_id))
    connection.commit()
    return max(0, int(cursor.rowcount))


def list_events(connection: sqlite3.Connection) -> list[Event]:
    return [Event(row[0], row[1], row[2], row[3], row[4], row[5], int(row[6]), bool(row[7]), row[8]) for row in connection.execute(
        """SELECT e.id, e.name, e.start_datetime, e.end_datetime, e.event_type,
                  e.description, COUNT(ea.asset_id), e.is_suggested, e.default_place_id
           FROM events e LEFT JOIN event_assets ea ON ea.event_id=e.id
           GROUP BY e.id ORDER BY COALESCE(e.start_datetime, e.created_at) DESC, e.name"""
    )]


def suggest_events_from_dates(connection: sqlite3.Connection, *, max_gap_days: int = 1, minimum_items: int = 2) -> int:
    """Create repeatable, low-confidence Event suggestions from capture dates."""
    if max_gap_days < 0 or minimum_items < 1:
        raise ValueError("invalid event suggestion settings")
    rows = list(connection.execute(
        """SELECT al.asset_id, substr(COALESCE(mm.capture_datetime, al.capture_date), 1, 10)
           FROM asset_locations al LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
           WHERE al.missing_since IS NULL AND COALESCE(mm.capture_datetime, al.capture_date) IS NOT NULL
           ORDER BY 2, al.asset_id"""
    ))
    groups: list[list[tuple[str, str]]] = []
    for asset_id, date_text in rows:
        current_date = datetime.fromisoformat(str(date_text)).date()
        if not groups:
            groups.append([(str(asset_id), str(date_text))])
            continue
        previous_date = datetime.fromisoformat(groups[-1][-1][1]).date()
        if current_date - previous_date <= timedelta(days=max_gap_days + 1):
            groups[-1].append((str(asset_id), str(date_text)))
        else:
            groups.append([(str(asset_id), str(date_text))])
    created = 0
    for group in groups:
        if len(group) < minimum_items:
            continue
        start, end = group[0][1], group[-1][1]
        name = f"Suggested · {start}" if start == end else f"Suggested · {start} – {end}"
        existing = connection.execute("SELECT id FROM events WHERE name=?", (name,)).fetchone()
        event_id = str(existing[0]) if existing else create_event(
            connection, name, start_datetime=start, end_datetime=end,
            event_type="other", is_suggested=True,
        )
        created += add_assets_to_event(connection, event_id, [asset_id for asset_id, _date in group], membership_source="suggested")
    return created


def create_tag(connection: sqlite3.Connection, name: str) -> str:
    clean = " ".join(name.strip().split())
    normalised = _normalise_tag(clean)
    existing = connection.execute("SELECT id FROM tags WHERE normalized_name=?", (normalised,)).fetchone()
    if existing:
        return str(existing[0])
    tag_id = str(uuid.uuid4())
    now = _now()
    connection.execute(
        "INSERT INTO tags(id, name, normalized_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (tag_id, clean, normalised, now, now),
    )
    connection.commit()
    return tag_id


def rename_tag(connection: sqlite3.Connection, tag_id: str, name: str) -> None:
    clean = " ".join(name.strip().split())
    normalised = _normalise_tag(clean)
    changed = connection.execute(
        "UPDATE tags SET name=?, normalized_name=?, updated_at=? WHERE id=?",
        (clean, normalised, _now(), tag_id),
    ).rowcount
    if not changed:
        raise ValueError("unknown tag")
    connection.commit()


def delete_tag(connection: sqlite3.Connection, tag_id: str) -> None:
    connection.execute("DELETE FROM asset_tags WHERE tag_id=?", (tag_id,))
    changed = connection.execute("DELETE FROM tags WHERE id=?", (tag_id,)).rowcount
    if not changed:
        raise ValueError("unknown tag")
    connection.commit()


def assign_tags(connection: sqlite3.Connection, asset_ids: list[str] | tuple[str, ...], tag_ids: list[str] | tuple[str, ...], *, source: str = "user") -> int:
    now = _now()
    cursor = connection.executemany(
        """INSERT OR IGNORE INTO asset_tags(asset_id, tag_id, source, created_at)
           SELECT a.id, ?, ?, ? FROM assets a WHERE a.id=?""",
        ((str(tag_id), source, now, str(asset_id)) for asset_id in dict.fromkeys(asset_ids) for tag_id in dict.fromkeys(tag_ids)),
    )
    connection.commit()
    return max(0, int(cursor.rowcount))


def remove_tags(connection: sqlite3.Connection, asset_ids: list[str] | tuple[str, ...], tag_ids: list[str] | tuple[str, ...]) -> int:
    cursor = connection.executemany(
        "DELETE FROM asset_tags WHERE asset_id=? AND tag_id=?",
        ((str(asset_id), str(tag_id)) for asset_id in dict.fromkeys(asset_ids) for tag_id in dict.fromkeys(tag_ids)),
    )
    connection.commit()
    return max(0, int(cursor.rowcount))


def list_tags(connection: sqlite3.Connection) -> list[Tag]:
    return [Tag(row[0], row[1], int(row[2])) for row in connection.execute(
        """SELECT t.id, t.name, COUNT(at.asset_id)
           FROM tags t LEFT JOIN asset_tags at ON at.tag_id=t.id
           GROUP BY t.id ORDER BY lower(t.name)"""
    )]


def set_review(connection: sqlite3.Connection, asset_ids: list[str] | tuple[str, ...], *, status: str | None = None, rating: int | None = None) -> int:
    if status is not None and status not in {"UNREVIEWED", "PICKED", "REJECTED", "HIDDEN"}:
        raise ValueError("invalid review status")
    if rating is not None and rating not in range(0, 6):
        raise ValueError("rating must be between 0 and 5")
    now = _now()
    changed = 0
    for asset_id in dict.fromkeys(str(item) for item in asset_ids):
        if connection.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone() is None:
            continue
        connection.execute(
            """INSERT INTO asset_reviews(asset_id, review_status, rating, updated_at)
               VALUES (?, COALESCE(?, 'UNREVIEWED'), ?, ?)
               ON CONFLICT(asset_id) DO UPDATE SET
                 review_status=COALESCE(excluded.review_status, asset_reviews.review_status),
                 rating=CASE WHEN ? IS NULL THEN asset_reviews.rating ELSE ? END,
                 updated_at=excluded.updated_at""",
            (asset_id, status, rating, now, rating, rating),
        )
        if rating == 0:
            # Review's 0 shortcut means clear the rating, not a visible zero-star rating.
            connection.execute("UPDATE asset_reviews SET rating=NULL, updated_at=? WHERE asset_id=?", (now, asset_id))
        changed += 1
    connection.commit()
    return changed


def create_place(connection: sqlite3.Connection, name: str, *, country: str | None = None, region: str | None = None, city: str | None = None, latitude: float | None = None, longitude: float | None = None) -> str:
    clean = " ".join(name.strip().split())
    if not clean:
        raise ValueError("place name is required")
    existing = connection.execute("SELECT id FROM places WHERE name=?", (clean,)).fetchone()
    if existing:
        return str(existing[0])
    place_id = str(uuid.uuid4())
    now = _now()
    connection.execute(
        """INSERT INTO places(id, name, country, region, city, latitude, longitude, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (place_id, clean, country, region, city, latitude, longitude, now, now),
    )
    connection.commit()
    return place_id


def assign_place(connection: sqlite3.Connection, asset_ids: list[str] | tuple[str, ...], place_id: str, *, source: str = "user_assigned") -> int:
    if connection.execute("SELECT 1 FROM places WHERE id=?", (place_id,)).fetchone() is None:
        raise ValueError("unknown place")
    now = _now()
    changed = 0
    for asset_id in dict.fromkeys(str(item) for item in asset_ids):
        if connection.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone() is None:
            continue
        connection.execute(
            """INSERT INTO asset_places(asset_id, place_id, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(asset_id) DO UPDATE SET place_id=excluded.place_id,
                 source=excluded.source, updated_at=excluded.updated_at""",
            (asset_id, place_id, source, now, now),
        )
        changed += 1
    connection.commit()
    return changed


def remove_place(connection: sqlite3.Connection, asset_ids: list[str] | tuple[str, ...], place_id: str) -> int:
    """Remove a catalog place assignment without touching embedded GPS or files."""
    cursor = connection.executemany(
        "DELETE FROM asset_places WHERE asset_id=? AND place_id=?",
        ((str(asset_id), str(place_id)) for asset_id in dict.fromkeys(asset_ids)),
    )
    connection.commit()
    return max(0, int(cursor.rowcount))


def update_place(connection: sqlite3.Connection, place_id: str, *, name: str, country: str | None = None, region: str | None = None, city: str | None = None, latitude: float | None = None, longitude: float | None = None) -> None:
    clean = " ".join(name.strip().split())
    if not clean:
        raise ValueError("place name is required")
    changed = connection.execute(
        "UPDATE places SET name=?, country=?, region=?, city=?, latitude=?, longitude=?, updated_at=? WHERE id=?",
        (clean, country, region, city, latitude, longitude, _now(), place_id),
    ).rowcount
    if not changed:
        raise ValueError("unknown place")
    connection.commit()


def delete_place(connection: sqlite3.Connection, place_id: str) -> None:
    connection.execute("DELETE FROM asset_places WHERE place_id=?", (place_id,))
    changed = connection.execute("DELETE FROM places WHERE id=?", (place_id,)).rowcount
    if not changed:
        raise ValueError("unknown place")
    connection.commit()


def list_places(connection: sqlite3.Connection) -> list[Place]:
    return [Place(row[0], row[1], row[2], row[3], row[4], int(row[5])) for row in connection.execute(
        """SELECT p.id, p.name, p.country, p.region, p.city, COUNT(ap.asset_id)
           FROM places p LEFT JOIN asset_places ap ON ap.place_id=p.id
           GROUP BY p.id ORDER BY lower(p.name)"""
    )]
