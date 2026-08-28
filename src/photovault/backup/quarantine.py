from __future__ import annotations

import json
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from photovault.catalog.hashing import sha256_file
from photovault.observability import log_event


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class QuarantineItem:
    asset_id: str
    volume_id: str
    relative_path: str
    source_path: Path
    destination_path: Path
    expected_sha256: str
    size_bytes: int


@dataclass(frozen=True)
class QuarantinePlan:
    operation_id: str
    reason: str
    manifest_path: Path
    items: tuple[QuarantineItem, ...]


def _catalogued_path(connection: sqlite3.Connection, path: Path):
    path = path.expanduser().resolve()
    candidates = []
    for row in connection.execute("SELECT id, current_mount_path FROM volumes WHERE current_mount_path IS NOT NULL"):
        root = Path(row[1]).expanduser().resolve()
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        candidates.append((len(root.parts), row[0], root, relative))
    if not candidates:
        raise ValueError(f"path is not under a registered volume: {path}")
    _, volume_id, root, relative = max(candidates, key=lambda candidate: candidate[0])
    row = connection.execute(
        "SELECT al.asset_id, al.size_bytes, eh.sha256 FROM asset_locations al "
        "JOIN exact_hashes eh ON eh.asset_id=al.asset_id "
        "WHERE al.volume_id=? AND al.relative_path=? AND al.missing_since IS NULL",
        (volume_id, relative),
    ).fetchone()
    if row is None:
        raise ValueError(f"path is not an active catalogued asset: {path}")
    return path, volume_id, root, relative, row


def _volume_relative(connection: sqlite3.Connection, path: Path) -> tuple[str, str]:
    path = path.expanduser().resolve()
    candidates = []
    for row in connection.execute("SELECT id, current_mount_path FROM volumes WHERE current_mount_path IS NOT NULL"):
        root = Path(row[1]).expanduser().resolve()
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        candidates.append((len(root.parts), row[0], relative))
    if not candidates:
        raise ValueError(f"path is not under a registered volume: {path}")
    _, volume_id, relative = max(candidates, key=lambda candidate: candidate[0])
    return volume_id, relative


def build_quarantine_plan(
    connection: sqlite3.Connection,
    paths: Iterable[Path],
    reason: str,
    quarantine_root: Path | None = None,
) -> QuarantinePlan:
    operation_id = "op_" + uuid.uuid4().hex
    resolved = [_catalogued_path(connection, Path(path)) for path in paths]
    if not resolved:
        raise ValueError("at least one path is required")
    if quarantine_root is None:
        root = resolved[0][2] / ".PhotoVaultQuarantine" / operation_id
    else:
        root = quarantine_root.expanduser().resolve() / operation_id
    items: list[QuarantineItem] = []
    for path, volume_id, volume_root, relative, row in resolved:
        if relative == ".PhotoVaultQuarantine" or relative.startswith(".PhotoVaultQuarantine/"):
            raise ValueError("a quarantine path cannot be quarantined again")
        if path == root or root in path.parents:
            raise ValueError("quarantine destination must not contain the source")
        items.append(QuarantineItem(row[0], volume_id, relative, path, root / relative, row[2], row[1]))
    details = {"reason": reason, "items": len(items), "manifest": str(root / "manifest.json")}
    connection.execute(
        "INSERT INTO operations(id, operation_type, created_at, status, dry_run, details_json) VALUES (?, 'QUARANTINE', ?, 'PLANNED', 1, ?)",
        (operation_id, _utc_now(), json.dumps(details, sort_keys=True)),
    )
    for item in items:
        connection.execute(
            "INSERT INTO operation_items(operation_id, asset_id, source_path, destination_path, expected_sha256, result) VALUES (?, ?, ?, ?, ?, 'PLANNED')",
            (operation_id, item.asset_id, str(item.source_path), str(item.destination_path), item.expected_sha256),
        )
    connection.commit()
    return QuarantinePlan(operation_id, reason, root / "manifest.json", tuple(items))


def _manifest(plan: QuarantinePlan) -> dict:
    return {
        "operation_id": plan.operation_id,
        "reason": plan.reason,
        "created_at": _utc_now(),
        "items": [
            {
                "asset_id": item.asset_id,
                "volume_id": item.volume_id,
                "original_path": str(item.source_path),
                "quarantine_path": str(item.destination_path),
                "relative_path": item.relative_path,
                "sha256": item.expected_sha256,
                "size_bytes": item.size_bytes,
            }
            for item in plan.items
        ],
    }


def execute_quarantine_plan(
    connection: sqlite3.Connection,
    plan: QuarantinePlan,
    move_fn: Callable[[str, str], object] = shutil.move,
) -> dict[str, int | str]:
    connection.execute("UPDATE operations SET status='RUNNING', dry_run=0, started_at=? WHERE id=?", (_utc_now(), plan.operation_id))
    plan.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    plan.manifest_path.write_text(json.dumps(_manifest(plan), indent=2, sort_keys=True), encoding="utf-8")
    connection.commit()
    started_clock = time.monotonic()
    log_event("quarantine_started", operation_id=plan.operation_id, asset_count=len(plan.items))
    moved = verified = failed = conflicts = 0
    for item in plan.items:
        op_item = connection.execute(
            "SELECT id FROM operation_items WHERE operation_id=? AND asset_id=? AND destination_path=?",
            (plan.operation_id, item.asset_id, str(item.destination_path)),
        ).fetchone()
        try:
            if sha256_file(item.source_path) != item.expected_sha256:
                failed += 1
                log_event("quarantine_item_failed", operation_id=plan.operation_id, asset_id=item.asset_id, path=str(item.source_path), error="source_changed")
                connection.execute("UPDATE operation_items SET result='SOURCE_CHANGED', verification_result='NOT_VERIFIED' WHERE id=?", (op_item[0],))
                continue
            if item.destination_path.exists():
                conflicts += 1
                log_event("quarantine_item_conflict", operation_id=plan.operation_id, asset_id=item.asset_id, path=str(item.destination_path), error="destination_exists")
                connection.execute("UPDATE operation_items SET result='CONFLICT', verification_result='NOT_VERIFIED', error_message='quarantine destination already exists' WHERE id=?", (op_item[0],))
                continue
            item.destination_path.parent.mkdir(parents=True, exist_ok=True)
            move_fn(str(item.source_path), str(item.destination_path))
            moved += 1
            actual = sha256_file(item.destination_path)
            if actual != item.expected_sha256:
                failed += 1
                log_event("quarantine_item_failed", operation_id=plan.operation_id, asset_id=item.asset_id, path=str(item.destination_path), error="post_move_verification_failed")
                connection.execute("UPDATE operation_items SET result='QUARANTINE_FAILED_VERIFICATION', verification_result='FAILED', error_message=? WHERE id=?", (f"expected {item.expected_sha256}, got {actual}", op_item[0]))
                continue
            verified += 1
            connection.execute(
                "UPDATE asset_locations SET missing_since=? WHERE asset_id=? AND volume_id=? AND relative_path=?",
                (_utc_now(), item.asset_id, item.volume_id, item.relative_path),
            )
            connection.execute("UPDATE operation_items SET result='QUARANTINED', verification_result='VERIFIED' WHERE id=?", (op_item[0],))
        except (OSError, ValueError) as exc:
            failed += 1
            log_event("quarantine_item_failed", operation_id=plan.operation_id, asset_id=item.asset_id, path=str(item.source_path), error=str(exc))
            connection.execute("UPDATE operation_items SET result='FAILED', verification_result='FAILED', error_message=? WHERE id=?", (str(exc), op_item[0]))
    status = "COMPLETED" if failed == 0 and conflicts == 0 else ("FAILED" if verified == 0 else "PARTIAL")
    connection.execute("UPDATE operations SET completed_at=?, status=? WHERE id=?", (_utc_now(), status, plan.operation_id))
    connection.commit()
    log_event(
        "quarantine_completed",
        operation_id=plan.operation_id,
        status=status,
        moved=moved,
        verified=verified,
        failed=failed,
        conflicts=conflicts,
        duration_ms=round((time.monotonic() - started_clock) * 1000),
    )
    return {"operation_id": plan.operation_id, "moved": moved, "verified": verified, "failed": failed, "conflicts": conflicts, "status": status}


def undo_quarantine(
    connection: sqlite3.Connection,
    operation_id: str,
    move_fn: Callable[[str, str], object] = shutil.move,
) -> dict[str, int | str]:
    operation = connection.execute("SELECT operation_type, status FROM operations WHERE id=?", (operation_id,)).fetchone()
    if operation is None or operation[0] != "QUARANTINE":
        raise ValueError(f"unknown quarantine operation: {operation_id}")
    rows = connection.execute(
        "SELECT id, asset_id, source_path, destination_path, expected_sha256 FROM operation_items "
        "WHERE operation_id=? AND result='QUARANTINED' ORDER BY id",
        (operation_id,),
    ).fetchall()
    undo_id = "op_" + uuid.uuid4().hex
    connection.execute(
        "INSERT INTO operations(id, operation_type, created_at, started_at, status, dry_run, details_json) VALUES (?, 'UNDO_QUARANTINE', ?, ?, 'RUNNING', 0, ?)",
        (undo_id, _utc_now(), _utc_now(), json.dumps({"quarantine_operation_id": operation_id}, sort_keys=True)),
    )
    restored = verified = failed = conflicts = 0
    for row in rows:
        _, asset_id, original, quarantined, expected = row
        op_item = connection.execute(
            "INSERT INTO operation_items(operation_id, asset_id, source_path, destination_path, expected_sha256, result) VALUES (?, ?, ?, ?, ?, 'PLANNED') RETURNING id",
            (undo_id, asset_id, quarantined, original, expected),
        ).fetchone()[0]
        try:
            qpath, opath = Path(quarantined), Path(original)
            if not qpath.exists():
                failed += 1
                connection.execute("UPDATE operation_items SET result='FAILED', verification_result='FAILED', error_message='quarantine file is missing' WHERE id=?", (op_item,))
                continue
            if sha256_file(qpath) != expected:
                failed += 1
                connection.execute("UPDATE operation_items SET result='SOURCE_CHANGED', verification_result='NOT_VERIFIED' WHERE id=?", (op_item,))
                continue
            if opath.exists():
                if sha256_file(opath) == expected:
                    verified += 1
                    volume_id, relative = _volume_relative(connection, opath)
                    connection.execute("UPDATE asset_locations SET missing_since=NULL WHERE asset_id=? AND volume_id=? AND relative_path=?", (asset_id, volume_id, relative))
                    connection.execute("UPDATE operation_items SET result='ALREADY_RESTORED', verification_result='VERIFIED' WHERE id=?", (op_item,))
                else:
                    conflicts += 1
                    connection.execute("UPDATE operation_items SET result='CONFLICT', verification_result='NOT_VERIFIED' WHERE id=?", (op_item,))
                continue
            opath.parent.mkdir(parents=True, exist_ok=True)
            move_fn(str(qpath), str(opath))
            restored += 1
            actual = sha256_file(opath)
            if actual != expected:
                failed += 1
                connection.execute("UPDATE operation_items SET result='UNDO_FAILED_VERIFICATION', verification_result='FAILED' WHERE id=?", (op_item,))
                continue
            verified += 1
            volume_id, relative = _volume_relative(connection, opath)
            connection.execute("UPDATE asset_locations SET missing_since=NULL WHERE asset_id=? AND volume_id=? AND relative_path=?", (asset_id, volume_id, relative))
            connection.execute("UPDATE operation_items SET result='RESTORED', verification_result='VERIFIED' WHERE id=?", (op_item,))
        except (OSError, ValueError) as exc:
            failed += 1
            connection.execute("UPDATE operation_items SET result='FAILED', verification_result='FAILED', error_message=? WHERE id=?", (str(exc), op_item))
    status = "COMPLETED" if failed == 0 and conflicts == 0 else ("FAILED" if verified == 0 else "PARTIAL")
    connection.execute("UPDATE operations SET completed_at=?, status=? WHERE id=?", (_utc_now(), status, undo_id))
    connection.commit()
    return {"operation_id": undo_id, "restored": restored, "verified": verified, "failed": failed, "conflicts": conflicts, "status": status}
