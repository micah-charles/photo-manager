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
    source_id: str = ""
    event_id: str = ""
    tag_id: str = ""
    place_id: str = ""
    category: str = ""
    review_status: str = ""
    min_rating: int | None = None
    include_rejected: bool = False
    asset_ids: tuple[str, ...] = ()
    sort: str = "captured_desc"
    limit: int = 200
    offset: int = 0


_SORTS = {
    "captured_desc": "display_captured IS NULL, display_captured DESC, al.relative_path",
    "captured_asc": "display_captured IS NULL, display_captured ASC, al.relative_path",
    "name_asc": "lower(al.filename), al.relative_path",
    "size_desc": "al.size_bytes DESC, al.relative_path",
}


def _where_for_query(query: LibraryQuery) -> tuple[list[str], list[object]]:
    """Build shared filters for list/count so both stay semantically identical."""
    if query.media_type not in {"ALL", "IMAGE", "VIDEO"}:
        raise ValueError("media_type must be ALL, IMAGE or VIDEO")
    if query.review_status and query.review_status not in {"UNREVIEWED", "PICKED", "REJECTED", "HIDDEN"}:
        raise ValueError("invalid review status")
    if query.min_rating is not None and query.min_rating not in range(0, 6):
        raise ValueError("min_rating must be between 0 and 5")
    where = ["al.missing_since IS NULL"]
    params: list[object] = []
    if not query.include_rejected and not query.review_status:
        where.append("COALESCE(ar.review_status, 'UNREVIEWED') NOT IN ('REJECTED', 'HIDDEN')")
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
    if query.source_id:
        where.append("al.source_id=?")
        params.append(query.source_id)
    if query.event_id:
        where.append("EXISTS (SELECT 1 FROM event_assets ea WHERE ea.asset_id=al.asset_id AND ea.event_id=? )")
        params.append(query.event_id)
    if query.tag_id:
        where.append("EXISTS (SELECT 1 FROM asset_tags at WHERE at.asset_id=al.asset_id AND at.tag_id=? )")
        params.append(query.tag_id)
    if query.place_id:
        where.append("EXISTS (SELECT 1 FROM asset_places ap WHERE ap.asset_id=al.asset_id AND ap.place_id=? )")
        params.append(query.place_id)
    if query.category:
        if ":" in query.category:
            model, label = query.category.split(":", 1)
            where.append("EXISTS (SELECT 1 FROM image_categories ic WHERE ic.asset_id=al.asset_id AND ic.model=? AND ic.label=? )")
            params.extend((model, label))
        else:
            where.append("EXISTS (SELECT 1 FROM image_categories ic WHERE ic.asset_id=al.asset_id AND ic.label=? )")
            params.append(query.category)
    if query.review_status:
        where.append("COALESCE(ar.review_status, 'UNREVIEWED')=?")
        params.append(query.review_status)
    if query.min_rating is not None:
        where.append("COALESCE(ar.rating, mm.rating, 0) >= ?")
        params.append(query.min_rating)
    if query.asset_ids:
        where.append("al.asset_id IN (" + ",".join("?" for _ in query.asset_ids) + ")")
        params.extend(query.asset_ids)
    return where, params


def list_library_items(connection: sqlite3.Connection, query: LibraryQuery = LibraryQuery()) -> list[sqlite3.Row]:
    """Return locations and cached metadata; offline originals stay visible."""
    if query.sort not in _SORTS:
        raise ValueError(f"unknown library sort: {query.sort}")
    if query.limit < 1 or query.offset < 0:
        raise ValueError("limit must be positive and offset cannot be negative")
    where, params = _where_for_query(query)
    sql = f"""
        SELECT al.asset_id, a.media_type, al.filename, al.relative_path, al.size_bytes,
               al.volume_id, v.display_name AS volume_name, v.status AS volume_status,
               v.current_mount_path,
               COALESCE(mm.capture_datetime, al.capture_date) AS captured,
               CASE WHEN COALESCE(mm.capture_datetime, al.capture_date) IS NOT NULL
                    THEN datetime(COALESCE(mm.capture_datetime, al.capture_date),
                                  printf('%+d seconds', COALESCE(sp.time_offset_seconds, 0)))
                    ELSE datetime(al.modified_ns / 1000000000, 'unixepoch') END AS display_captured,
               mm.camera_make, mm.camera_model, mm.width, mm.height,
               gm.latitude, gm.longitude, mm.date_source,
               th.path AS thumbnail_path,
               EXISTS (SELECT 1 FROM asset_favourites f WHERE f.asset_id=al.asset_id) AS is_favourite,
               al.source_id, sp.display_name AS source_name,
               COALESCE(ar.review_status, 'UNREVIEWED') AS review_status,
               COALESCE(ar.rating, mm.rating) AS rating,
               (SELECT group_concat(e.name, ', ') FROM event_assets ea
                JOIN events e ON e.id=ea.event_id WHERE ea.asset_id=al.asset_id) AS event_names,
               (SELECT group_concat(t.name, ', ') FROM asset_tags at
                JOIN tags t ON t.id=at.tag_id WHERE at.asset_id=al.asset_id) AS tag_names,
               (SELECT group_concat(p.name, ', ') FROM asset_places ap
                JOIN places p ON p.id=ap.place_id WHERE ap.asset_id=al.asset_id) AS place_names
        FROM asset_locations al
        JOIN assets a ON a.id=al.asset_id
        JOIN volumes v ON v.id=al.volume_id
        LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
        LEFT JOIN gps_metadata gm ON gm.asset_id=al.asset_id
        LEFT JOIN thumbnails th ON th.asset_id=al.asset_id AND th.version='v1-320'
        LEFT JOIN source_profiles sp ON sp.source_id=al.source_id
        LEFT JOIN asset_reviews ar ON ar.asset_id=al.asset_id
        WHERE {' AND '.join(where)}
        ORDER BY {_SORTS[query.sort]}
        LIMIT ? OFFSET ?
    """
    params.extend((query.limit, query.offset))
    return list(connection.execute(sql, params))


def count_library_items(connection: sqlite3.Connection, query: LibraryQuery = LibraryQuery()) -> int:
    """Count items using exactly the same filter semantics as the page query."""
    unbounded = LibraryQuery(**{**query.__dict__, "limit": 1, "offset": 0})
    # Querying the filtered IDs via a subquery keeps this count in lockstep with
    # list_library_items without scanning raw folders.
    where, params = _where_for_query(unbounded)
    return int(connection.execute(
        f"""SELECT COUNT(*) FROM asset_locations al JOIN assets a ON a.id=al.asset_id
            LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
            LEFT JOIN asset_reviews ar ON ar.asset_id=al.asset_id
            WHERE {' AND '.join(where)}""",
        params,
    ).fetchone()[0])
