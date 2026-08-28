from __future__ import annotations

import sqlite3
from pathlib import Path

from .migrations import apply_migrations


def connect(catalog_path: Path | str) -> sqlite3.Connection:
    catalog_value = str(catalog_path)
    if catalog_value == ":memory:":
        connection = sqlite3.connect(":memory:")
    else:
        resolved_path = Path(catalog_path).expanduser().resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(resolved_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    apply_migrations(connection)
    return connection
