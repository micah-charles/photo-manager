from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path


RECONCILIATION_STATUSES = {"VERIFIED", "MAIN_ONLY", "BACKUP_ONLY", "CONFLICT", "UNKNOWN_OFFLINE"}


@dataclass(frozen=True)
class ReconciliationItem:
    status: str
    main_path: str | None
    backup_path: str | None
    main_asset_id: str | None
    backup_asset_id: str | None
    main_sha256: str | None
    backup_sha256: str | None
    reason: str


@dataclass(frozen=True)
class ReconciliationReport:
    backup_set_id: str
    name: str
    primary_volume_id: str
    backup_volume_id: str
    items: tuple[ReconciliationItem, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {status: sum(item.status == status for item in self.items) for status in sorted(RECONCILIATION_STATUSES)}

    def write_csv(self, path: Path) -> None:
        path = path.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow([
                "status", "main_path", "backup_path", "main_asset_id", "backup_asset_id",
                "main_sha256", "backup_sha256", "reason",
            ])
            for item in self.items:
                writer.writerow([
                    item.status, item.main_path or "", item.backup_path or "",
                    item.main_asset_id or "", item.backup_asset_id or "",
                    item.main_sha256 or "", item.backup_sha256 or "", item.reason,
                ])


def _in_scope(path: str, prefix: str) -> bool:
    return not prefix or path == prefix or path.startswith(prefix + "/")


def _locations(connection: sqlite3.Connection, set_id: str, volume_id: str, scope: str, relative_root: str):
    rows = connection.execute(
        "SELECT al.asset_id, al.relative_path, eh.sha256, v.status "
        "FROM asset_locations al JOIN exact_hashes eh ON eh.asset_id=al.asset_id "
        "JOIN volumes v ON v.id=al.volume_id "
        "WHERE al.volume_id=? AND al.missing_since IS NULL",
        (volume_id,),
    ).fetchall()
    return [row for row in rows if _in_scope(row[1], scope) and _in_scope(row[1], relative_root)]


def reconcile_backup_set(
    connection: sqlite3.Connection,
    backup_set_id: str,
    backup_volume_id: str | None = None,
) -> ReconciliationReport:
    backup_set = connection.execute(
        "SELECT id, name, scope FROM backup_sets WHERE id=?", (backup_set_id,)
    ).fetchone()
    if backup_set is None:
        raise ValueError(f"unknown backup set: {backup_set_id}")
    members = connection.execute(
        "SELECT bsm.volume_id, bsm.role, bsm.relative_root, v.status FROM backup_set_members bsm "
        "JOIN volumes v ON v.id=bsm.volume_id WHERE bsm.backup_set_id=? ORDER BY bsm.volume_id",
        (backup_set_id,),
    ).fetchall()
    primaries = [row for row in members if row[1] == "PRIMARY"]
    backups = [row for row in members if row[1] == "BACKUP"]
    if len(primaries) != 1:
        raise ValueError("a backup set must have exactly one PRIMARY member")
    if not backups:
        raise ValueError("a backup set must have at least one BACKUP member")
    backup = next((row for row in backups if row[0] == backup_volume_id), None) if backup_volume_id else backups[0]
    if backup is None:
        raise ValueError(f"backup volume is not a member of backup set: {backup_volume_id}")
    primary = primaries[0]
    main_rows = _locations(connection, backup_set_id, primary[0], backup_set[2], primary[2])
    backup_rows = _locations(connection, backup_set_id, backup[0], backup_set[2], backup[2])
    main_by_path = {row[1]: row for row in main_rows}
    backup_by_path = {row[1]: row for row in backup_rows}
    used_main: set[int] = set()
    used_backup: set[int] = set()
    items: list[ReconciliationItem] = []
    offline = primary[3] != "CONNECTED" or backup[3] != "CONNECTED"

    for path in sorted(set(main_by_path) & set(backup_by_path)):
        main = main_by_path[path]
        back = backup_by_path[path]
        main_index, backup_index = main_rows.index(main), backup_rows.index(back)
        used_main.add(main_index)
        used_backup.add(backup_index)
        if offline:
            status, reason = "UNKNOWN_OFFLINE", "primary or backup volume is offline"
        elif main[2] == back[2]:
            status, reason = "VERIFIED", "same SHA-256 content at the same relative path"
        else:
            status, reason = "CONFLICT", "same relative path has different SHA-256 content"
        items.append(ReconciliationItem(status, main[1], back[1], main[0], back[0], main[2], back[2], reason))

    if offline:
        for index, main in enumerate(main_rows):
            if index not in used_main:
                items.append(ReconciliationItem("UNKNOWN_OFFLINE", main[1], None, main[0], None, main[2], None, "primary or backup volume is offline"))
        for index, back in enumerate(backup_rows):
            if index not in used_backup:
                items.append(ReconciliationItem("UNKNOWN_OFFLINE", None, back[1], None, back[0], None, back[2], "primary or backup volume is offline"))
    else:
        by_hash: dict[str, list[int]] = {}
        for index, back in enumerate(backup_rows):
            if index not in used_backup:
                by_hash.setdefault(back[2], []).append(index)
        for index, main in enumerate(main_rows):
            if index in used_main:
                continue
            candidates = by_hash.get(main[2], [])
            if candidates:
                backup_index = candidates.pop(0)
                used_main.add(index)
                used_backup.add(backup_index)
                back = backup_rows[backup_index]
                items.append(ReconciliationItem("VERIFIED", main[1], back[1], main[0], back[0], main[2], back[2], "same SHA-256 content at different relative paths"))
        for index, main in enumerate(main_rows):
            if index not in used_main:
                items.append(ReconciliationItem("MAIN_ONLY", main[1], None, main[0], None, main[2], None, "no matching SHA-256 content on backup"))
        for index, back in enumerate(backup_rows):
            if index not in used_backup:
                items.append(ReconciliationItem("BACKUP_ONLY", None, back[1], None, back[0], None, back[2], "no matching SHA-256 content on primary"))
    return ReconciliationReport(backup_set[0], backup_set[1], primary[0], backup[0], tuple(items))
