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
    recently_added: bool = False
    captured_from: str = ""
    captured_to: str = ""
    captured_month: str = ""
    source_id: str = ""
    event_id: str = ""
    tag_id: str = ""
    place_id: str = ""
    person_id: str = ""
    import_batch_id: str = ""
    category: str = ""
    review_status: str = ""
    min_rating: int | None = None
    include_rejected: bool = False
    asset_ids: tuple[str, ...] = ()
    sort: str = "captured_desc"
    limit: int = 200
    offset: int = 0
    after_captured: str = ""
    after_asset_id: str = ""


_SORTS = {
    "captured_desc": "display_captured IS NULL, display_captured DESC, al.relative_path",
    "captured_desc_id": "display_captured IS NULL, display_captured DESC, al.asset_id",
    "captured_asc": "display_captured IS NULL, display_captured ASC, al.relative_path",
    "name_asc": "lower(al.filename), al.relative_path",
    "size_desc": "al.size_bytes DESC, al.relative_path",
}


def _display_captured_expr() -> str:
    """Return the catalog's single capture-time expression used by the UI."""
    return "CASE WHEN COALESCE(mm.capture_datetime, al.capture_date) IS NOT NULL THEN datetime(COALESCE(mm.capture_datetime, al.capture_date), printf('%+d seconds', COALESCE(sp.time_offset_seconds, 0))) ELSE datetime(al.modified_ns / 1000000000, 'unixepoch') END"


def library_facets(connection: sqlite3.Connection, query: LibraryQuery = LibraryQuery()) -> list[dict[str, object]]:
    """Return complete month navigation facets, independent of page size/cursor."""
    facet_query = LibraryQuery(**{
        **query.__dict__,
        "captured_month": "",
        "captured_from": "",
        "captured_to": "",
        "after_captured": "",
        "after_asset_id": "",
        "limit": 1,
        "offset": 0,
    })
    where, params = _where_for_query(facet_query)
    captured_expr = _display_captured_expr()
    rows = connection.execute(
        f"""SELECT substr({captured_expr}, 1, 7) AS month, COUNT(DISTINCT al.asset_id) AS item_count
            FROM asset_locations al
            JOIN assets a ON a.id=al.asset_id
            LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
            LEFT JOIN asset_reviews ar ON ar.asset_id=al.asset_id
            LEFT JOIN source_profiles sp ON sp.source_id=al.source_id
            WHERE {' AND '.join(where)} AND {captured_expr} IS NOT NULL
            GROUP BY 1 ORDER BY 1 DESC""",
        params,
    ).fetchall()
    return [{"key": str(row[0]), "label": str(row[0]).replace("-", " / "), "item_count": int(row[1])} for row in rows]


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
        where.append(
            """(lower(al.filename) LIKE ? OR lower(al.relative_path) LIKE ?
                OR lower(COALESCE(mm.capture_datetime, al.capture_date, '')) LIKE ?
                OR EXISTS (SELECT 1 FROM source_profiles sp_search
                           WHERE sp_search.source_id=al.source_id
                             AND lower(sp_search.display_name) LIKE ?)
                OR EXISTS (SELECT 1 FROM event_assets ea_search JOIN events e_search ON e_search.id=ea_search.event_id
                           WHERE ea_search.asset_id=al.asset_id AND lower(e_search.name) LIKE ?)
                OR EXISTS (SELECT 1 FROM asset_tags at_search JOIN tags t_search ON t_search.id=at_search.tag_id
                           WHERE at_search.asset_id=al.asset_id AND lower(t_search.name) LIKE ?)
                OR EXISTS (SELECT 1 FROM person_members pm_search JOIN people p_search ON p_search.id=pm_search.person_id
                           WHERE pm_search.asset_id=al.asset_id AND lower(COALESCE(p_search.display_name, p_search.external_key)) LIKE ?)
                OR EXISTS (SELECT 1 FROM asset_places ap_search JOIN places pl_search ON pl_search.id=ap_search.place_id
                           WHERE ap_search.asset_id=al.asset_id AND lower(pl_search.name) LIKE ?)
                OR EXISTS (SELECT 1 FROM event_assets ea_place_search JOIN events e_place_search ON e_place_search.id=ea_place_search.event_id
                           JOIN places pl_event_search ON pl_event_search.id=e_place_search.default_place_id
                           WHERE ea_place_search.asset_id=al.asset_id AND lower(pl_event_search.name) LIKE ?)
                OR EXISTS (SELECT 1 FROM image_categories ic_search
                           WHERE ic_search.asset_id=al.asset_id AND lower(ic_search.label) LIKE ?))"""
        )
        term = "%" + query.search.strip().lower() + "%"
        params.extend((term,) * 10)
    if query.folder_prefix.strip("/"):
        where.append("al.relative_path LIKE ?")
        params.append(query.folder_prefix.strip("/") + "/%")
    if query.media_type != "ALL":
        where.append("a.media_type=?")
        params.append(query.media_type)
    if query.favourite_only:
        where.append("EXISTS (SELECT 1 FROM asset_favourites f WHERE f.asset_id=al.asset_id)")
    if query.recently_added:
        where.append("a.created_at >= datetime('now', '-30 days')")
    if query.captured_from:
        where.append(f"{_display_captured_expr()} >= ?")
        params.append(query.captured_from)
    if query.captured_to:
        where.append(f"{_display_captured_expr()} <= ?")
        params.append(query.captured_to)
    if query.captured_month:
        # Library displays modified time when embedded capture time is absent.
        # Apply the same fallback to month navigation, otherwise the month
        # rail can show a month whose selection returns no rows.
        where.append(
            f"substr({_display_captured_expr()}, 1, 7) = ?"
        )
        params.append(query.captured_month)
    if query.source_id:
        source_ids = tuple(source for source in query.source_id.split(",") if source)
        if len(source_ids) == 1:
            where.append("al.source_id=?")
            params.append(source_ids[0])
        elif source_ids:
            where.append("al.source_id IN (" + ",".join("?" for _ in source_ids) + ")")
            params.extend(source_ids)
    if query.event_id:
        where.append("EXISTS (SELECT 1 FROM event_assets ea WHERE ea.asset_id=al.asset_id AND ea.event_id=? )")
        params.append(query.event_id)
    if query.tag_id:
        where.append("EXISTS (SELECT 1 FROM asset_tags at WHERE at.asset_id=al.asset_id AND at.tag_id=? )")
        params.append(query.tag_id)
    if query.place_id:
        where.append("(EXISTS (SELECT 1 FROM asset_places ap WHERE ap.asset_id=al.asset_id AND ap.place_id=? ) OR EXISTS (SELECT 1 FROM event_assets ea JOIN events e ON e.id=ea.event_id WHERE ea.asset_id=al.asset_id AND e.default_place_id=?))")
        params.extend((query.place_id, query.place_id))
    if query.person_id:
        where.append("EXISTS (SELECT 1 FROM person_members pm WHERE pm.asset_id=al.asset_id AND pm.person_id=? )")
        params.append(query.person_id)
    if query.import_batch_id:
        where.append("EXISTS (SELECT 1 FROM source_imports si JOIN exact_hashes eh ON eh.sha256=si.sha256 WHERE si.batch_id=? AND eh.asset_id=al.asset_id)")
        params.append(query.import_batch_id)
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
    if query.after_asset_id:
        captured_expr = _display_captured_expr()
        if query.after_captured:
            where.append(f"(({captured_expr} IS NULL) OR {captured_expr} < ? OR ({captured_expr} = ? AND al.asset_id > ?))")
            params.extend((query.after_captured, query.after_captured, query.after_asset_id))
        else:
            where.append(f"{captured_expr} IS NULL AND al.asset_id > ?")
            params.append(query.after_asset_id)
    return where, params


def list_library_items(connection: sqlite3.Connection, query: LibraryQuery = LibraryQuery()) -> list[sqlite3.Row]:
    """Return locations and cached metadata; offline originals stay visible."""
    if query.sort not in _SORTS:
        raise ValueError(f"unknown library sort: {query.sort}")
    if query.limit < 1 or query.offset < 0:
        raise ValueError("limit must be positive and offset cannot be negative")
    where, params = _where_for_query(query)
    order_by = "a.created_at DESC, al.relative_path" if query.recently_added else _SORTS[query.sort]
    sql = f"""
        SELECT al.asset_id, a.media_type, al.filename, al.relative_path, al.size_bytes,
               al.volume_id, v.display_name AS volume_name, v.status AS volume_status,
               v.current_mount_path,
               a.created_at AS imported_at,
               COALESCE(mm.capture_datetime, al.capture_date) AS captured,
               CASE WHEN COALESCE(mm.capture_datetime, al.capture_date) IS NOT NULL
                    THEN datetime(COALESCE(mm.capture_datetime, al.capture_date),
                                  printf('%+d seconds', COALESCE(sp.time_offset_seconds, 0)))
                    ELSE datetime(al.modified_ns / 1000000000, 'unixepoch') END AS display_captured,
               mm.camera_make, mm.camera_model, mm.width, mm.height, mm.orientation,
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
               ,(SELECT group_concat(p.name, ', ') FROM event_assets ea
                 JOIN events e ON e.id=ea.event_id JOIN places p ON p.id=e.default_place_id
                 WHERE ea.asset_id=al.asset_id
                   AND NOT EXISTS (SELECT 1 FROM asset_places ap2 WHERE ap2.asset_id=al.asset_id)) AS inherited_place_names
               ,(SELECT group_concat(COALESCE(p.display_name, p.external_key), ', ') FROM person_members pm
                 JOIN people p ON p.id=pm.person_id WHERE pm.asset_id=al.asset_id) AS person_names
        FROM asset_locations al
        JOIN assets a ON a.id=al.asset_id
        JOIN volumes v ON v.id=al.volume_id
        LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
        LEFT JOIN gps_metadata gm ON gm.asset_id=al.asset_id
        LEFT JOIN thumbnails th ON th.asset_id=al.asset_id AND th.version='v1-320'
        LEFT JOIN source_profiles sp ON sp.source_id=al.source_id
        LEFT JOIN asset_reviews ar ON ar.asset_id=al.asset_id
        WHERE {' AND '.join(where)}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
    """
    params.extend((query.limit, query.offset))
    return list(connection.execute(sql, params))


def library_day_counts(connection: sqlite3.Connection, query: LibraryQuery = LibraryQuery()) -> dict[str, int]:
    """Return complete day counts for the current filters, independent of page size."""
    unpaged = LibraryQuery(**{
        **query.__dict__,
        "after_captured": "",
        "after_asset_id": "",
        "limit": 1,
        "offset": 0,
    })
    where, params = _where_for_query(unpaged)
    captured_expr = _display_captured_expr()
    day_expr = f"substr({captured_expr}, 1, 10)"
    rows = connection.execute(
        f"""SELECT {day_expr} AS day, COUNT(*) AS item_count
            FROM asset_locations al
            JOIN assets a ON a.id=al.asset_id
            LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
            LEFT JOIN asset_reviews ar ON ar.asset_id=al.asset_id
            LEFT JOIN source_profiles sp ON sp.source_id=al.source_id
            WHERE {' AND '.join(where)} AND {captured_expr} IS NOT NULL
            GROUP BY 1 ORDER BY 1 DESC""",
        params,
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def library_asset_ids(connection: sqlite3.Connection, query: LibraryQuery = LibraryQuery()) -> list[str]:
    """Return every matching asset id for an explicit bulk-selection action."""
    unpaged = LibraryQuery(**{
        **query.__dict__,
        "after_captured": "",
        "after_asset_id": "",
        "limit": 1,
        "offset": 0,
    })
    where, params = _where_for_query(unpaged)
    rows = connection.execute(
        f"""SELECT DISTINCT al.asset_id
            FROM asset_locations al
            JOIN assets a ON a.id=al.asset_id
            LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
            LEFT JOIN asset_reviews ar ON ar.asset_id=al.asset_id
            LEFT JOIN source_profiles sp ON sp.source_id=al.source_id
            WHERE {' AND '.join(where)}
            ORDER BY al.asset_id""",
        params,
    ).fetchall()
    return [str(row[0]) for row in rows]


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
            LEFT JOIN source_profiles sp ON sp.source_id=al.source_id
            WHERE {' AND '.join(where)}""",
        params,
    ).fetchone()[0])
