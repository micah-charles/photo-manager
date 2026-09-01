"""Paged, catalog-backed library browsing without rescanning media folders."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class LibraryQuery:
    search: str = ""
    folder_prefix: str = ""
    media_type: str = "ALL"
    favourite_only: bool = False
    captured_from: str = ""
    captured_to: str = ""
    captured_month: str = ""
    asset_ids: tuple[str, ...] = ()
    sort: str = "captured_desc"
    limit: int = 200
    offset: int = 0


_SORTS = {
    "captured_desc": "captured IS NULL, captured DESC, al.relative_path",
    "captured_asc": "captured IS NULL, captured ASC, al.relative_path",
    "name_asc": "lower(al.filename), al.relative_path",
    "size_desc": "al.size_bytes DESC, al.relative_path",
}


def list_library_items(connection: sqlite3.Connection, query: LibraryQuery = LibraryQuery()) -> list[sqlite3.Row]:
    """Return locations and cached metadata; offline originals stay visible."""
    if query.media_type not in {"ALL", "IMAGE", "VIDEO"}:
        raise ValueError("media_type must be ALL, IMAGE or VIDEO")
    if query.sort not in _SORTS:
        raise ValueError(f"unknown library sort: {query.sort}")
    if query.limit < 1 or query.offset < 0:
        raise ValueError("limit must be positive and offset cannot be negative")
    where = ["al.missing_since IS NULL"]
    params: list[object] = []
    if query.search.strip():
        where.append("(lower(al.filename) LIKE ? OR lower(al.relative_path) LIKE ?)")
        term = "%" + query.search.strip().lower() + "%"
        params.extend((term, term))
    if query.folder_prefix.strip("/"):
        where.append("al.relative_path LIKE ?")
        params.append(query.folder_prefix.strip("/") + "/%")
    if query.media_type != "ALL":
        where.append("a.media_type=?")
        params.append(query.media_type)
    if query.favourite_only:
        where.append("EXISTS (SELECT 1 FROM asset_favourites f WHERE f.asset_id=al.asset_id)")
    if query.captured_from:
        where.append("COALESCE(mm.capture_datetime, al.capture_date) >= ?")
        params.append(query.captured_from)
    if query.captured_to:
        where.append("COALESCE(mm.capture_datetime, al.capture_date) <= ?")
        params.append(query.captured_to)
    if query.captured_month:
        where.append("substr(COALESCE(mm.capture_datetime, al.capture_date), 1, 7) = ?")
        params.append(query.captured_month)
    if query.asset_ids:
        where.append("al.asset_id IN (" + ",".join("?" for _ in query.asset_ids) + ")")
        params.extend(query.asset_ids)
    sql = f"""
        SELECT al.asset_id, a.media_type, al.filename, al.relative_path, al.size_bytes,
               al.volume_id, v.display_name AS volume_name, v.status AS volume_status,
               v.current_mount_path,
               COALESCE(mm.capture_datetime, al.capture_date) AS captured,
               mm.camera_make, mm.camera_model, mm.width, mm.height,
               th.path AS thumbnail_path,
               EXISTS (SELECT 1 FROM asset_favourites f WHERE f.asset_id=al.asset_id) AS is_favourite
        FROM asset_locations al
        JOIN assets a ON a.id=al.asset_id
        JOIN volumes v ON v.id=al.volume_id
        LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
        LEFT JOIN thumbnails th ON th.asset_id=al.asset_id AND th.version='v1-320'
        WHERE {' AND '.join(where)}
        ORDER BY {_SORTS[query.sort]}
        LIMIT ? OFFSET ?
    """
    params.extend((query.limit, query.offset))
    return list(connection.execute(sql, params))


def count_library_items(connection: sqlite3.Connection, query: LibraryQuery = LibraryQuery()) -> int:
    """Count items using exactly the same filter semantics as the page query."""
    unbounded = LibraryQuery(
        search=query.search, folder_prefix=query.folder_prefix, media_type=query.media_type,
        favourite_only=query.favourite_only, captured_from=query.captured_from,
        captured_to=query.captured_to, captured_month=query.captured_month,
        asset_ids=query.asset_ids, sort=query.sort, limit=1, offset=0,
    )
    # Querying the filtered IDs via a subquery keeps this count in lockstep with
    # list_library_items without scanning raw folders.
    where = ["al.missing_since IS NULL"]
    params: list[object] = []
    if unbounded.search.strip():
        where.append("(lower(al.filename) LIKE ? OR lower(al.relative_path) LIKE ?)")
        term = "%" + unbounded.search.strip().lower() + "%"
        params.extend((term, term))
    if unbounded.folder_prefix.strip("/"):
        where.append("al.relative_path LIKE ?")
        params.append(unbounded.folder_prefix.strip("/") + "/%")
    if unbounded.media_type != "ALL":
        where.append("a.media_type=?")
        params.append(unbounded.media_type)
    if unbounded.favourite_only:
        where.append("EXISTS (SELECT 1 FROM asset_favourites f WHERE f.asset_id=al.asset_id)")
    if unbounded.captured_from:
        where.append("COALESCE(mm.capture_datetime, al.capture_date) >= ?")
        params.append(unbounded.captured_from)
    if unbounded.captured_to:
        where.append("COALESCE(mm.capture_datetime, al.capture_date) <= ?")
        params.append(unbounded.captured_to)
    if unbounded.captured_month:
        where.append("substr(COALESCE(mm.capture_datetime, al.capture_date), 1, 7) = ?")
        params.append(unbounded.captured_month)
    if unbounded.asset_ids:
        where.append("al.asset_id IN (" + ",".join("?" for _ in unbounded.asset_ids) + ")")
        params.extend(unbounded.asset_ids)
    return int(connection.execute(
        f"""SELECT COUNT(*) FROM asset_locations al JOIN assets a ON a.id=al.asset_id
            LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
            WHERE {' AND '.join(where)}""",
        params,
    ).fetchone()[0])
