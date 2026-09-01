from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Iterable

from photovault.sources.base import PhotoItem, SourceIdentity


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def register_source(connection: sqlite3.Connection, identity: SourceIdentity) -> None:
    now = _now()
    connection.execute(
        """
        INSERT INTO source_profiles(
            id, source_id, manufacturer, model, display_name, adapter,
            usb_vendor_id, usb_product_id, first_seen, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            manufacturer=excluded.manufacturer, model=excluded.model,
            display_name=excluded.display_name, adapter=excluded.adapter,
            usb_vendor_id=excluded.usb_vendor_id, usb_product_id=excluded.usb_product_id,
            last_seen=excluded.last_seen
        """,
        (
            identity.source_id,
            identity.source_id,
            identity.manufacturer,
            identity.model,
            identity.display_name,
            identity.adapter,
            identity.usb_vendor_id,
            identity.usb_product_id,
            now,
            now,
        ),
    )
    connection.commit()


def record_source_items(
    connection: sqlite3.Connection,
    source_id: str,
    items: Iterable[PhotoItem],
    logical_prefix: str = "",
) -> int:
    now = _now()
    count = 0
    for item in items:
        logical_path = "/".join(part for part in (logical_prefix, item.name) if part)
        connection.execute(
            """
            INSERT INTO source_items(
                source_id, object_id, logical_path, name, media_type, size_bytes,
                created_at, modified_at, source_latitude, source_longitude, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, logical_path) DO UPDATE SET
                object_id=excluded.object_id, name=excluded.name,
                media_type=excluded.media_type, size_bytes=excluded.size_bytes,
                created_at=excluded.created_at, modified_at=excluded.modified_at,
                source_latitude=excluded.source_latitude, source_longitude=excluded.source_longitude,
                last_seen=excluded.last_seen
            """,
            (
                source_id,
                item.object_id,
                logical_path,
                item.name,
                item.media_type,
                item.size_bytes,
                item.created_at.isoformat() if item.created_at else None,
                item.modified_at.isoformat() if item.modified_at else None,
                item.source_latitude,
                item.source_longitude,
                now,
            ),
        )
        count += 1
    connection.commit()
    return count
