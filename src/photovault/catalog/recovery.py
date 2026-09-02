"""Consistent SQLite catalog backup and integrity checks."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CatalogBackupResult:
    source: Path
    destination: Path
    bytes_written: int
    integrity: tuple[str, ...]


def check_catalog_integrity(catalog_path: Path) -> tuple[str, ...]:
    """Return SQLite's integrity-check output without mutating the catalog."""
    catalog = catalog_path.expanduser().resolve()
    if not catalog.is_file():
        raise ValueError(f"catalog does not exist: {catalog}")
    connection = sqlite3.connect(catalog)
    try:
        return tuple(str(row[0]) for row in connection.execute("PRAGMA integrity_check"))
    finally:
        connection.close()


def backup_catalog(catalog_path: Path, destination_path: Path) -> CatalogBackupResult:
    """Create a new consistent backup via SQLite's online backup API.

    The destination is deliberately required not to exist. Restoring is a
    separate explicit user action; this function never replaces a live catalog.
    """
    source_path = catalog_path.expanduser().resolve()
    destination = destination_path.expanduser().resolve()
    if not source_path.is_file():
        raise ValueError(f"catalog does not exist: {source_path}")
    if source_path == destination:
        raise ValueError("catalog backup destination must differ from the source")
    if destination.exists():
        raise FileExistsError(f"catalog backup destination already exists: {destination}")
    if not destination.parent.is_dir():
        raise ValueError(f"catalog backup parent does not exist: {destination.parent}")
    source = sqlite3.connect(source_path)
    destination_connection = sqlite3.connect(destination)
    try:
        source.backup(destination_connection)
        integrity = tuple(str(row[0]) for row in destination_connection.execute("PRAGMA integrity_check"))
    finally:
        destination_connection.close()
        source.close()
    if integrity != ("ok",):
        raise RuntimeError(f"catalog backup integrity check failed: {integrity}")
    return CatalogBackupResult(source_path, destination, destination.stat().st_size, integrity)


def restore_catalog(backup_path: Path, destination_path: Path) -> CatalogBackupResult:
    """Create a verified working catalog from a backup without overwriting either file."""
    return backup_catalog(backup_path, destination_path)
