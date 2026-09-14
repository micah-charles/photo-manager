from __future__ import annotations

from datetime import date
import sqlite3


def list_timeline(
    connection: sqlite3.Connection,
    volume_id: str | None = None,
    limit: int = 100,
    source_id: str | None = None,
    offset: int = 0,
    start_date: str | None = None,
    end_date: str | None = None,
):
    if limit < 1:
        raise ValueError("limit must be positive")
    if offset < 0:
        raise ValueError("offset must not be negative")
    for label, value in (("start_date", start_date), ("end_date", end_date)):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{label} must use YYYY-MM-DD") from exc
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    display_expression = (
        "datetime(COALESCE(mm.capture_datetime, al.capture_date), "
        "printf('%+d seconds', COALESCE(sp.time_offset_seconds, 0)))"
    )
    query = (
        "SELECT al.asset_id, al.filename, al.relative_path, al.volume_id, "
        "COALESCE(mm.capture_datetime, al.capture_date) AS captured, "
        "CASE WHEN COALESCE(mm.capture_datetime, al.capture_date) IS NOT NULL "
        f"THEN {display_expression} "
        "ELSE NULL END AS display_captured, "
        "mm.camera_make, mm.camera_model, mm.width, mm.height, gm.latitude, gm.longitude, "
        "sp.display_name AS source_name, th.path "
        "FROM asset_locations al LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id "
        "LEFT JOIN gps_metadata gm ON gm.asset_id=al.asset_id "
        "LEFT JOIN thumbnails th ON th.asset_id=al.asset_id AND th.version='v1-320' "
        "LEFT JOIN source_profiles sp ON sp.source_id=al.source_id "
        "WHERE al.missing_since IS NULL"
    )
    params: list[object] = []
    if volume_id:
        query += " AND al.volume_id=?"
        params.append(volume_id)
    if source_id:
        query += " AND al.source_id=?"
        params.append(source_id)
    if start_date:
        query += f" AND date({display_expression}) >= date(?)"
        params.append(start_date)
    if end_date:
        query += f" AND date({display_expression}) <= date(?)"
        params.append(end_date)
    query += " ORDER BY display_captured IS NULL, display_captured DESC, al.relative_path LIMIT ? OFFSET ?"
    params.extend((limit, offset))
    return connection.execute(query, params).fetchall()
