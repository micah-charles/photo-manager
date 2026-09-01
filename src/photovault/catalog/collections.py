"""Safe, catalog-derived browsing collections.

Collections are views over evidence already in the catalog.  They never rename,
copy, tag, or otherwise mutate original media.  Optional people and semantic
collections will later use the same interface, but must record their engine and
provenance explicitly.
"""
from __future__ import annotations

import sqlite3
import uuid
from collections import Counter
from dataclasses import dataclass

from .library import LibraryQuery, count_library_items, list_library_items


@dataclass(frozen=True)
class CatalogCollection:
    id: str
    kind: str
    title: str
    item_count: int
    detail: str = ""
    cover_path: str | None = None


def list_collections(connection: sqlite3.Connection) -> list[CatalogCollection]:
    """List useful browse views without touching a media file."""
    result: list[CatalogCollection] = []
    favourites = int(connection.execute("SELECT COUNT(*) FROM asset_favourites").fetchone()[0])
    if favourites:
        result.append(CatalogCollection("favourites", "FAVOURITES", "Favourites", favourites, "catalog annotations"))

    months = connection.execute(
        """SELECT substr(COALESCE(mm.capture_datetime, al.capture_date), 1, 7), COUNT(DISTINCT al.asset_id)
           FROM asset_locations al LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
           WHERE al.missing_since IS NULL AND COALESCE(mm.capture_datetime, al.capture_date) IS NOT NULL
           GROUP BY 1 ORDER BY 1 DESC"""
    )
    result.extend(CatalogCollection(f"month:{month}", "DATE", str(month), int(count), "capture month") for month, count in months)

    folders: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    for asset_id, relative_path in connection.execute("SELECT asset_id, relative_path FROM asset_locations WHERE missing_since IS NULL"):
        folder = str(relative_path).rsplit("/", 1)[0] if "/" in str(relative_path) else "/"
        if (asset_id, folder) not in seen:
            folders[folder] += 1; seen.add((asset_id, folder))
    result.extend(CatalogCollection(f"folder:{folder}", "FOLDER", folder, count, "source folder") for folder, count in sorted(folders.items(), key=lambda row: (-row[1], row[0])))

    for row in connection.execute(
        """SELECT p.id, p.label, p.centroid_latitude, p.centroid_longitude, COUNT(m.asset_id)
           FROM place_clusters p JOIN place_cluster_members m ON m.cluster_id=p.id
           GROUP BY p.id ORDER BY COUNT(m.asset_id) DESC, p.id"""
    ):
        label = row[1] or f"{row[2]:.4f}, {row[3]:.4f}"
        result.append(CatalogCollection(f"place:{row[0]}", "PLACE", label, int(row[4]), "embedded GPS only"))

    for row in connection.execute(
        """SELECT g.id, g.group_type, g.algorithm, COUNT(m.asset_id)
           FROM duplicate_groups g JOIN duplicate_group_members m ON m.group_id=g.id
           GROUP BY g.id ORDER BY COUNT(m.asset_id) DESC, g.id"""
    ):
        result.append(CatalogCollection(f"duplicate:{row[0]}", "VISUAL", f"{row[1].replace('_', ' ').title()} #{row[0][-6:]}", int(row[3]), f"{row[2]}; advisory only"))
    for row in connection.execute(
        """SELECT p.id, p.display_name, p.engine, COUNT(m.asset_id)
           FROM people p JOIN person_members m ON m.person_id=p.id
           GROUP BY p.id ORDER BY COUNT(m.asset_id) DESC, p.id"""
    ):
        result.append(CatalogCollection(f"person:{row[0]}", "PERSON", row[1] or f"Person {row[0][-6:]}", int(row[3]), f"{row[2]}; derived face group"))
    for row in connection.execute(
        """SELECT model, label, COUNT(DISTINCT asset_id) FROM image_categories
           GROUP BY model, label HAVING COUNT(DISTINCT asset_id) >= 2
           ORDER BY COUNT(DISTINCT asset_id) DESC, model, label"""
    ):
        result.append(CatalogCollection(f"category:{row[0]}:{row[1]}", "CATEGORY", row[1], int(row[2]), f"{row[0]}; local model candidate"))
    for row in connection.execute(
        """SELECT c.id, c.title, COUNT(m.asset_id), c.updated_at,
                  (SELECT t.path FROM user_collection_members cm
                   JOIN thumbnails t ON t.asset_id=cm.asset_id AND t.version='default'
                   WHERE cm.collection_id=c.id ORDER BY cm.added_at, cm.asset_id LIMIT 1)
           FROM user_collections c LEFT JOIN user_collection_members m ON m.collection_id=c.id
           GROUP BY c.id ORDER BY c.title"""
    ):
        result.append(CatalogCollection(f"user:{row[0]}", "ALBUM", row[1], int(row[2]), "user-created album", row[4]))
    return result


def collection_query(connection: sqlite3.Connection, collection_id: str, *, limit: int = 200, offset: int = 0) -> LibraryQuery:
    """Resolve a collection identifier to a normal, safe library query."""
    if collection_id == "favourites":
        return LibraryQuery(favourite_only=True, limit=limit, offset=offset)
    if collection_id.startswith("month:"):
        month = collection_id[6:]
        if len(month) != 7 or month[4] != "-" or not month.replace("-", "").isdigit():
            raise ValueError("invalid month collection")
        return LibraryQuery(captured_month=month, limit=limit, offset=offset)
    if collection_id.startswith("folder:"):
        return LibraryQuery(folder_prefix=collection_id[7:], limit=limit, offset=offset)
    if collection_id.startswith("place:"):
        rows = connection.execute("SELECT asset_id FROM place_cluster_members WHERE cluster_id=? ORDER BY asset_id", (collection_id[6:],)).fetchall()
    elif collection_id.startswith("duplicate:"):
        rows = connection.execute("SELECT asset_id FROM duplicate_group_members WHERE group_id=? ORDER BY asset_id", (collection_id[10:],)).fetchall()
    elif collection_id.startswith("person:"):
        rows = connection.execute("SELECT asset_id FROM person_members WHERE person_id=? ORDER BY asset_id", (collection_id[7:],)).fetchall()
    elif collection_id.startswith("category:"):
        try:
            _, model, label = collection_id.split(":", 2)
        except ValueError as exc:
            raise ValueError("invalid category collection") from exc
        rows = connection.execute("SELECT asset_id FROM image_categories WHERE model=? AND label=? ORDER BY score DESC, asset_id", (model, label)).fetchall()
    elif collection_id.startswith("user:"):
        rows = connection.execute(
            "SELECT asset_id FROM user_collection_members WHERE collection_id=? ORDER BY added_at, asset_id",
            (collection_id[5:],),
        ).fetchall()
    else:
        raise ValueError("unknown collection")
    if not rows:
        raise ValueError("collection has no members")
    return LibraryQuery(asset_ids=tuple(str(row[0]) for row in rows), limit=limit, offset=offset)


def list_collection_items(connection: sqlite3.Connection, collection_id: str, *, limit: int = 200, offset: int = 0) -> list[sqlite3.Row]:
    return list_library_items(connection, collection_query(connection, collection_id, limit=limit, offset=offset))


def count_collection_items(connection: sqlite3.Connection, collection_id: str) -> int:
    return count_library_items(connection, collection_query(connection, collection_id, limit=1))


def create_user_collection(connection: sqlite3.Connection, title: str) -> str:
    """Create an album in the catalog; original media is never touched."""
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("collection title is required")
    collection_id = str(uuid.uuid4())
    now = "datetime('now')"
    connection.execute(
        f"INSERT INTO user_collections(id, title, created_at, updated_at) VALUES (?, ?, {now}, {now})",
        (collection_id, clean_title),
    )
    connection.commit()
    return f"user:{collection_id}"


def add_to_user_collection(connection: sqlite3.Connection, collection_id: str, asset_ids: list[str] | tuple[str, ...]) -> int:
    """Add catalog assets to an album idempotently, without copying or moving files."""
    if collection_id.startswith("user:"):
        collection_id = collection_id[5:]
    exists = connection.execute("SELECT 1 FROM user_collections WHERE id=?", (collection_id,)).fetchone()
    if exists is None:
        raise ValueError("unknown user collection")
    cursor = connection.executemany(
        "INSERT OR IGNORE INTO user_collection_members(collection_id, asset_id, added_at) VALUES (?, ?, datetime('now'))",
        ((collection_id, asset_id) for asset_id in dict.fromkeys(str(item) for item in asset_ids)),
    )
    connection.execute("UPDATE user_collections SET updated_at=datetime('now') WHERE id=?", (collection_id,))
    connection.commit()
    return max(0, int(cursor.rowcount))
