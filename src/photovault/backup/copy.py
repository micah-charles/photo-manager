from __future__ import annotations

import json
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from photovault.backup.reconcile import reconcile_backup_set
from photovault.catalog.hashing import sha256_file
from photovault.catalog.sources import register_source
from photovault.observability import log_event
from photovault.sources.base import SourceIdentity


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class CopyPlanItem:
    asset_id: str
    source_path: Path
    destination_path: Path
    relative_path: str
    expected_sha256: str
    size_bytes: int


@dataclass(frozen=True)
class CopyPlan:
    operation_id: str
    backup_set_id: str
    primary_volume_id: str
    backup_volume_id: str
    items: tuple[CopyPlanItem, ...]

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)


def build_copy_plan(connection: sqlite3.Connection, backup_set_id: str, backup_volume_id: str | None = None) -> CopyPlan:
    report = reconcile_backup_set(connection, backup_set_id, backup_volume_id)
    primary = connection.execute(
        "SELECT current_mount_path FROM volumes WHERE id=?", (report.primary_volume_id,)
    ).fetchone()
    backup = connection.execute(
        "SELECT current_mount_path FROM volumes WHERE id=?", (report.backup_volume_id,)
    ).fetchone()
    states = connection.execute(
        "SELECT status FROM volumes WHERE id IN (?, ?)",
        (report.primary_volume_id, report.backup_volume_id),
    ).fetchall()
    if primary is None or backup is None or any(row[0] != "CONNECTED" for row in states):
        raise RuntimeError("both primary and backup volumes must be connected to create a copy plan")

    items: list[CopyPlanItem] = []
    for reconciliation_item in report.items:
        if reconciliation_item.status != "MAIN_ONLY":
            continue
        relative_path = reconciliation_item.main_path
        if relative_path is None or reconciliation_item.main_asset_id is None or reconciliation_item.main_sha256 is None:
            continue
        source = connection.execute(
            "SELECT size_bytes FROM asset_locations WHERE asset_id=? AND volume_id=? AND relative_path=? AND missing_since IS NULL",
            (reconciliation_item.main_asset_id, report.primary_volume_id, relative_path),
        ).fetchone()
        if source is None:
            continue
        items.append(CopyPlanItem(
            reconciliation_item.main_asset_id,
            Path(primary[0]) / relative_path,
            Path(backup[0]) / relative_path,
            relative_path,
            reconciliation_item.main_sha256,
            source[0],
        ))
    operation_id = "op_" + uuid.uuid4().hex
    details = {"backup_set_id": backup_set_id, "items": len(items), "bytes": sum(item.size_bytes for item in items)}
    connection.execute(
        "INSERT INTO operations(id, operation_type, created_at, status, dry_run, details_json) VALUES (?, 'COPY', ?, 'PLANNED', 1, ?)",
        (operation_id, _utc_now(), json.dumps(details, sort_keys=True)),
    )
    for item in items:
        connection.execute(
            "INSERT INTO operation_items(operation_id, asset_id, source_path, destination_path, expected_sha256, result) VALUES (?, ?, ?, ?, ?, 'PLANNED')",
            (operation_id, item.asset_id, str(item.source_path), str(item.destination_path), item.expected_sha256),
        )
    connection.commit()
    return CopyPlan(operation_id, backup_set_id, report.primary_volume_id, report.backup_volume_id, tuple(items))


def _record_destination(connection: sqlite3.Connection, plan: CopyPlan, item: CopyPlanItem) -> None:
    stat = item.destination_path.stat()
    source_id = f"folder:{plan.backup_volume_id}"
    volume = connection.execute(
        "SELECT display_name FROM volumes WHERE id=?", (plan.backup_volume_id,)
    ).fetchone()
    register_source(connection, SourceIdentity(
        source_id=source_id,
        manufacturer="Local filesystem",
        model="Folder / removable media",
        display_name=str(volume[0] if volume else plan.backup_volume_id),
        adapter="local_folder",
    ))
    # Upgrade a pre-provenance destination row rather than creating a second
    # location for the same physical path.
    connection.execute(
        "UPDATE asset_locations SET source_id=? "
        "WHERE volume_id=? AND relative_path=? AND source_id IS NULL",
        (source_id, plan.backup_volume_id, item.relative_path),
    )
    connection.execute(
        """
        INSERT INTO asset_locations(asset_id, volume_id, relative_path, filename, size_bytes, modified_ns, source_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(volume_id, relative_path, source_id) DO UPDATE SET
          asset_id=excluded.asset_id, filename=excluded.filename, size_bytes=excluded.size_bytes,
          modified_ns=excluded.modified_ns, missing_since=NULL
        """,
        (item.asset_id, plan.backup_volume_id, item.relative_path, item.destination_path.name, stat.st_size, stat.st_mtime_ns, source_id),
    )


def execute_copy_plan(
    connection: sqlite3.Connection,
    plan: CopyPlan,
    copy_fn: Callable[[str, str], object] = shutil.copy2,
) -> dict[str, int | str]:
    """Execute a reviewed plan; never overwrites an existing conflicting destination."""
    connection.execute(
        "UPDATE operations SET status='RUNNING', dry_run=0, started_at=? WHERE id=?",
        (_utc_now(), plan.operation_id),
    )
    connection.commit()
    started_clock = time.monotonic()
    log_event("copy_started", operation_id=plan.operation_id, asset_count=len(plan.items))
    copied = verified = failed = conflicts = 0
    for item in plan.items:
        op_item = connection.execute(
            "SELECT id FROM operation_items WHERE operation_id=? AND asset_id=? AND destination_path=?",
            (plan.operation_id, item.asset_id, str(item.destination_path)),
        ).fetchone()
        try:
            source_actual = sha256_file(item.source_path)
            if source_actual != item.expected_sha256:
                failed += 1
                log_event("copy_item_failed", operation_id=plan.operation_id, asset_id=item.asset_id, path=str(item.source_path), error="source_changed")
                connection.execute(
                    "UPDATE operation_items SET result='SOURCE_CHANGED', verification_result='NOT_VERIFIED', error_message=? WHERE id=?",
                    (f"expected {item.expected_sha256}, got {source_actual}", op_item[0]),
                )
                continue
            if item.destination_path.exists():
                actual = sha256_file(item.destination_path)
                if actual == item.expected_sha256:
                    result, verification = "ALREADY_PRESENT", "VERIFIED"
                    verified += 1
                    _record_destination(connection, plan, item)
                    connection.execute(
                        "INSERT INTO verification_history(operation_item_id, asset_id, path, expected_sha256, actual_sha256, result, verified_at) VALUES (?, ?, ?, ?, ?, 'VERIFIED', ?)",
                        (op_item[0], item.asset_id, str(item.destination_path), item.expected_sha256, actual, _utc_now()),
                    )
                else:
                    result, verification = "CONFLICT", "NOT_VERIFIED"
                    conflicts += 1
                    log_event("copy_item_conflict", operation_id=plan.operation_id, asset_id=item.asset_id, path=str(item.destination_path), error="destination_hash_mismatch")
                connection.execute(
                    "UPDATE operation_items SET result=?, verification_result=?, error_message=? WHERE id=?",
                    (result, verification, "destination exists with different SHA-256" if result == "CONFLICT" else None, op_item[0]),
                )
                continue
            item.destination_path.parent.mkdir(parents=True, exist_ok=True)
            copy_fn(str(item.source_path), str(item.destination_path))
            copied += 1
            actual = sha256_file(item.destination_path)
            if actual != item.expected_sha256:
                failed += 1
                log_event("copy_item_failed", operation_id=plan.operation_id, asset_id=item.asset_id, path=str(item.destination_path), error="destination_verification_failed")
                connection.execute(
                    "UPDATE operation_items SET result='COPY_FAILED_VERIFICATION', verification_result='FAILED', error_message=? WHERE id=?",
                    (f"expected {item.expected_sha256}, got {actual}", op_item[0]),
                )
                connection.execute(
                    "INSERT INTO verification_history(operation_item_id, asset_id, path, expected_sha256, actual_sha256, result, verified_at) VALUES (?, ?, ?, ?, ?, 'FAILED', ?)",
                    (op_item[0], item.asset_id, str(item.destination_path), item.expected_sha256, actual, _utc_now()),
                )
                continue
            verified += 1
            _record_destination(connection, plan, item)
            connection.execute(
                "UPDATE operation_items SET result='COPIED', verification_result='VERIFIED' WHERE id=?",
                (op_item[0],),
            )
            connection.execute(
                "INSERT INTO verification_history(operation_item_id, asset_id, path, expected_sha256, actual_sha256, result, verified_at) VALUES (?, ?, ?, ?, ?, 'VERIFIED', ?)",
                (op_item[0], item.asset_id, str(item.destination_path), item.expected_sha256, actual, _utc_now()),
            )
        except (OSError, ValueError) as exc:
            failed += 1
            log_event("copy_item_failed", operation_id=plan.operation_id, asset_id=item.asset_id, path=str(item.source_path), error=str(exc))
            connection.execute(
                "UPDATE operation_items SET result='FAILED', verification_result='FAILED', error_message=? WHERE id=?",
                (str(exc), op_item[0]),
            )
    status = "COMPLETED" if failed == 0 and conflicts == 0 else ("FAILED" if verified == 0 else "PARTIAL")
    connection.execute(
        "UPDATE operations SET completed_at=?, status=? WHERE id=?",
        (_utc_now(), status, plan.operation_id),
    )
    connection.commit()
    log_event(
        "copy_completed",
        operation_id=plan.operation_id,
        status=status,
        copied=copied,
        verified=verified,
        failed=failed,
        conflicts=conflicts,
        duration_ms=round((time.monotonic() - started_clock) * 1000),
    )
    return {"operation_id": plan.operation_id, "copied": copied, "verified": verified, "failed": failed, "conflicts": conflicts, "status": status}
