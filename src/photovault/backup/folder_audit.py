from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from photovault.catalog.scanner import iter_media


@dataclass(frozen=True)
class FolderAuditItem:
    relative_path: str
    status: str
    asset_id: str | None
    other_paths: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class FolderAuditReport:
    folder: Path
    volume_id: str
    files_scanned: int
    verified_elsewhere: int
    unique_files: int
    conflicts: int
    offline_unknown: int
    uncatalogued: int
    items: tuple[FolderAuditItem, ...]

    @property
    def safe_candidate(self) -> bool:
        return (
            self.files_scanned > 0
            and self.unique_files == 0
            and self.conflicts == 0
            and self.offline_unknown == 0
            and self.uncatalogued == 0
        )


def _folder_member(connection: sqlite3.Connection, folder: Path):
    folder = folder.expanduser().resolve()
    candidates = []
    for row in connection.execute("SELECT id, current_mount_path, status FROM volumes WHERE current_mount_path IS NOT NULL"):
        root = Path(row[1]).expanduser().resolve()
        try:
            relative = folder.relative_to(root).as_posix()
        except ValueError:
            continue
        candidates.append((len(root.parts), row[0], root, "" if relative == "." else relative, row[2]))
    if not candidates:
        raise ValueError(f"folder is not under a registered volume: {folder}")
    return folder, max(candidates, key=lambda candidate: candidate[0])


def audit_folder(connection: sqlite3.Connection, folder: Path) -> FolderAuditReport:
    folder, (_, volume_id, volume_root, folder_relative, volume_status) = _folder_member(connection, folder)
    if not folder.is_dir():
        raise ValueError(f"folder is not available: {folder}")
    prefix = folder_relative.strip("/")
    prefix_sql = prefix + "/" if prefix else ""
    rows = connection.execute(
        "SELECT al.id, al.asset_id, al.relative_path, eh.sha256 "
        "FROM asset_locations al JOIN exact_hashes eh ON eh.asset_id=al.asset_id "
        "WHERE al.volume_id=? AND al.missing_since IS NULL AND "
        "(al.relative_path=? OR al.relative_path LIKE ?)",
        (volume_id, prefix, prefix_sql + "%"),
    ).fetchall()
    by_relative = {row[2][len(prefix_sql):] if prefix_sql else row[2]: row for row in rows}
    actual_paths = {
        path.relative_to(folder).as_posix()
        for path, _ in iter_media(folder)
    }
    items: list[FolderAuditItem] = []
    verified = unique = conflicts = offline_unknown = 0
    for relative_path in sorted(actual_paths | set(by_relative)):
        source = by_relative.get(relative_path)
        if source is None:
            items.append(FolderAuditItem(relative_path, "UNCATALOGUED", None, (), "file is not present in the catalog"))
            continue
        other_rows = connection.execute(
            "SELECT al.relative_path, al.asset_id, v.status "
            "FROM asset_locations al JOIN volumes v ON v.id=al.volume_id "
            "WHERE al.asset_id=? AND al.id<>? AND al.missing_since IS NULL",
            (source[1], source[0]),
        ).fetchall()
        connected_others = [row for row in other_rows if row[2] == "CONNECTED"]
        offline_others = [row for row in other_rows if row[2] != "CONNECTED"]
        basename_conflict = connection.execute(
            "SELECT al.relative_path, eh.sha256 FROM asset_locations al "
            "JOIN exact_hashes eh ON eh.asset_id=al.asset_id "
            "WHERE al.volume_id<>? AND al.filename=? AND al.missing_since IS NULL AND eh.sha256<>? LIMIT 1",
            (volume_id, Path(relative_path).name, source[3]),
        ).fetchone()
        if basename_conflict is not None:
            status, reason = "CONFLICT", "another volume has the same filename with different SHA-256 content"
            conflicts += 1
            paths = (basename_conflict[0],)
        elif connected_others:
            status, reason = "VERIFIED_ELSEWHERE", "an active exact-content copy exists elsewhere"
            verified += 1
            paths = tuple(row[0] for row in connected_others)
        elif offline_others:
            status, reason = "UNKNOWN_OFFLINE", "only known copies elsewhere are on offline volumes"
            offline_unknown += 1
            paths = tuple(row[0] for row in offline_others)
        else:
            status, reason = "UNIQUE", "no other active exact-content location is catalogued"
            unique += 1
            paths = ()
        items.append(FolderAuditItem(relative_path, status, source[1], paths, reason))
    return FolderAuditReport(
        folder, volume_id, len(actual_paths), verified, unique, conflicts,
        offline_unknown, sum(item.status == "UNCATALOGUED" for item in items), tuple(items),
    )
