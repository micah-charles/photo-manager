from __future__ import annotations

import sqlite3
from pathlib import Path


def refresh_volume_statuses(connection: sqlite3.Connection) -> dict[str, int]:
    """Mark catalogued volumes connected/offline from their last mount path.

    This is deliberately an explicit refresh: business reports preserve a
    previously recorded OFFLINE state until the user reconnects/registers or
    refreshes the volume. It never scans or changes media.
    """
    connected = offline = 0
    for row in connection.execute("SELECT id, current_mount_path FROM volumes").fetchall():
        is_connected = bool(row[1]) and Path(row[1]).expanduser().is_dir()
        status = "CONNECTED" if is_connected else "OFFLINE"
        connection.execute("UPDATE volumes SET status=? WHERE id=?", (status, row[0]))
        if is_connected:
            connected += 1
        else:
            offline += 1
    connection.commit()
    return {"connected": connected, "offline": offline}
