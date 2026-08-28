from __future__ import annotations

import sqlite3
from dataclasses import dataclass


STATUSES = {
    "VERIFIED_REDUNDANT", "MISSING_BACKUP", "BACKUP_ONLY", "CONFLICT",
    "UNPROTECTED", "MULTI_COPY", "OFFLINE_UNKNOWN",
}


@dataclass(frozen=True)
class AuditItem:
    asset_id: str
    status: str
    primary_paths: tuple[str, ...]
    backup_paths: tuple[str, ...]
    copy_count: int
    reason: str


@dataclass(frozen=True)
class AuditReport:
    backup_set_id: str
    name: str
    required_copies: int
    total_assets: int
    items: tuple[AuditItem, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {status: sum(item.status == status for item in self.items) for status in sorted(STATUSES)}

    @property
    def protected_count(self) -> int:
        return self.counts.get("VERIFIED_REDUNDANT", 0) + self.counts.get("MULTI_COPY", 0)

    @property
    def protection_percent(self) -> float:
        return (self.protected_count / self.total_assets * 100) if self.total_assets else 100.0


def _in_scope(path: str, prefix: str) -> bool:
    return not prefix or path == prefix or path.startswith(prefix + "/")


def audit_backup_set(connection: sqlite3.Connection, backup_set_id: str) -> AuditReport:
    backup_set = connection.execute(
        "SELECT id, name, required_copies, scope FROM backup_sets WHERE id=?", (backup_set_id,)
    ).fetchone()
    if backup_set is None:
        raise ValueError(f"unknown backup set: {backup_set_id}")
    members = connection.execute(
        "SELECT bsm.volume_id, bsm.role, bsm.relative_root, v.status "
        "FROM backup_set_members bsm JOIN volumes v ON v.id=bsm.volume_id "
        "WHERE bsm.backup_set_id=? ORDER BY bsm.role, bsm.volume_id",
        (backup_set_id,),
    ).fetchall()
    primary_members = [row for row in members if row[1] == "PRIMARY"]
    backup_members = [row for row in members if row[1] == "BACKUP"]
    if len(primary_members) != 1:
        raise ValueError("a backup set must have exactly one PRIMARY member")
    primary = primary_members[0]

    rows = connection.execute(
        "SELECT al.asset_id, al.volume_id, al.relative_path, al.missing_since, "
        "eh.sha256, v.status "
        "FROM asset_locations al JOIN backup_set_members bsm ON bsm.volume_id=al.volume_id "
        "JOIN volumes v ON v.id=al.volume_id LEFT JOIN exact_hashes eh ON eh.asset_id=al.asset_id "
        "WHERE bsm.backup_set_id=? AND al.missing_since IS NULL",
        (backup_set_id,),
    ).fetchall()
    observations: dict[str, list[sqlite3.Row]] = {}
    member_by_volume = {member[0]: member for member in members}
    for row in rows:
        member = member_by_volume[row[1]]
        if _in_scope(row[2], backup_set[3]) and _in_scope(row[2], member[2]):
            observations.setdefault(row[0], []).append(row)

    all_primary_rows = [row for asset_rows in observations.values() for row in asset_rows if row[1] == primary[0]]
    all_backup_rows = [row for asset_rows in observations.values() for row in asset_rows if row[1] != primary[0]]
    conflict_asset_ids = {
        row[0]
        for p in all_primary_rows
        for b in all_backup_rows
        if p[2] == b[2] and p[4] is not None and b[4] is not None and p[4] != b[4]
        for row in (p, b)
    }

    items: list[AuditItem] = []
    for asset_id, asset_rows in sorted(observations.items()):
        primary_rows = [row for row in asset_rows if row[1] == primary[0]]
        backup_rows = [row for row in asset_rows if row[1] != primary[0]]
        primary_paths = tuple(row[2] for row in primary_rows)
        backup_paths = tuple(row[2] for row in backup_rows)
        known_volume_ids = {row[1] for row in asset_rows if row[5] == "CONNECTED"}
        offline_required = any(member[3] != "CONNECTED" for member in [primary, *backup_members])
        if asset_id in conflict_asset_ids:
            status, reason = "CONFLICT", "same relative path has different SHA-256 content"
        elif offline_required:
            status, reason = "OFFLINE_UNKNOWN", "a required backup-set volume is offline"
        elif not primary_rows and backup_rows:
            status, reason = "BACKUP_ONLY", "no active location exists on the primary volume"
        elif primary_rows:
            copy_count = len(known_volume_ids)
            if copy_count >= 3:
                status, reason = "MULTI_COPY", "three or more connected volumes contain this exact asset"
            elif copy_count >= backup_set[2]:
                status, reason = "VERIFIED_REDUNDANT", "required connected copies share the same SHA-256 asset"
            elif backup_members:
                status, reason = "MISSING_BACKUP", "the primary asset has fewer than the required copies"
            else:
                status, reason = "UNPROTECTED", "no backup member is configured"
        else:
            continue
        items.append(AuditItem(asset_id, status, primary_paths, backup_paths, len(known_volume_ids), reason))
    return AuditReport(backup_set[0], backup_set[1], backup_set[2], len(items), tuple(items))
