"""Actionable catalog metrics for the desktop dashboard."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class DashboardMetrics:
    assets: int
    images: int
    videos: int
    catalog_bytes: int
    volumes: int
    connected_volumes: int
    sources: int
    backup_profiles: int
    last_backup: str | None
    favourites: int
    places: int
    duplicate_groups: int
    active_operations: int


def dashboard_metrics(connection: sqlite3.Connection) -> DashboardMetrics:
    """Read concise metrics only; this does not scan, hash, or enrich media."""
    counts = {
        row[0]: int(row[1])
        for row in connection.execute("SELECT media_type, COUNT(*) FROM assets GROUP BY media_type")
    }
    catalog_bytes = int(connection.execute("PRAGMA page_count").fetchone()[0]) * int(
        connection.execute("PRAGMA page_size").fetchone()[0]
    )
    return DashboardMetrics(
        assets=sum(counts.values()), images=counts.get("IMAGE", 0), videos=counts.get("VIDEO", 0),
        catalog_bytes=catalog_bytes,
        volumes=int(connection.execute("SELECT COUNT(*) FROM volumes").fetchone()[0]),
        connected_volumes=int(connection.execute("SELECT COUNT(*) FROM volumes WHERE status='CONNECTED'").fetchone()[0]),
        sources=int(connection.execute("SELECT COUNT(*) FROM source_profiles").fetchone()[0]),
        backup_profiles=int(connection.execute("SELECT COUNT(*) FROM android_backup_profiles").fetchone()[0]),
        last_backup=connection.execute(
            "SELECT completed_at FROM android_backup_snapshots WHERE status='COMPLETED' ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()[0] if connection.execute("SELECT COUNT(*) FROM android_backup_snapshots WHERE status='COMPLETED'").fetchone()[0] else None,
        favourites=int(connection.execute("SELECT COUNT(*) FROM asset_favourites").fetchone()[0]),
        places=int(connection.execute("SELECT COUNT(*) FROM place_clusters").fetchone()[0]),
        duplicate_groups=int(connection.execute("SELECT COUNT(*) FROM duplicate_groups").fetchone()[0]),
        active_operations=int(connection.execute("SELECT COUNT(*) FROM operations WHERE status IN ('RUNNING', 'PARTIAL')").fetchone()[0]),
    )
