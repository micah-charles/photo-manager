"""Safe, catalog-derived browsing collections.

Collections are views over evidence already in the catalog.  They never rename,
copy, tag, or otherwise mutate original media.  Optional people and semantic
collections will later use the same interface, but must record their engine and
provenance explicitly.
"""
from __future__ import annotations

import sqlite3
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
    else:
        raise ValueError("unknown collection")
    if not rows:
        raise ValueError("collection has no members")
    return LibraryQuery(asset_ids=tuple(str(row[0]) for row in rows), limit=limit, offset=offset)


def list_collection_items(connection: sqlite3.Connection, collection_id: str, *, limit: int = 200, offset: int = 0) -> list[sqlite3.Row]:
    return list_library_items(connection, collection_query(connection, collection_id, limit=limit, offset=offset))


def count_collection_items(connection: sqlite3.Connection, collection_id: str) -> int:
    return count_library_items(connection, collection_query(connection, collection_id, limit=1))
