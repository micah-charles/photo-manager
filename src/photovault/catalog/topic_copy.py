"""Safe, non-destructive export of the files belonging to a topic.

This is deliberately separate from backup-set copy. A topic copy is a user
requested filesystem export: it does not create catalog locations, mutate
topics, or move/delete any source file.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .hashing import sha256_file
from .library import visible_asset_sql


_INVALID_COMPONENT = re.compile(r"[\\/:*?\"<>|\x00\r\n]+")
_MAX_COMPONENT_LENGTH = 120


def _safe_component(value: str, fallback: str) -> str:
    """Make a human-readable, platform-safe folder component."""
    result = _INVALID_COMPONENT.sub("_", str(value or "")).strip().strip(".")
    result = re.sub(r"\s+", " ", result)
    if not result or result in {".", ".."}:
        result = fallback
    return result[:_MAX_COMPONENT_LENGTH].rstrip(".") or fallback


def _safe_relative_path(value: str) -> Path:
    """Resolve a catalog path without allowing it to escape its source root."""
    raw = str(value or "")
    if not raw or "\x00" in raw:
        raise ValueError("catalog location has an invalid relative path")
    path = Path(raw.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("catalog location is not a safe relative path")
    return path


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class TopicCopyItem:
    asset_id: str
    filename: str
    source_id: str
    source_name: str
    source_root: Path
    source_path: Path
    relative_path: str
    destination_path: Path
    size_bytes: int


@dataclass(frozen=True)
class TopicCopyPlan:
    topic_id: str
    topic_name: str
    destination: Path
    include_raw: bool
    items: tuple[TopicCopyItem, ...]
    missing: tuple[dict[str, str], ...]

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)

    def payload(self) -> dict[str, object]:
        source_counts = Counter(item.source_name for item in self.items)
        return {
            "ok": True,
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "destination": str(self.destination),
            "include_raw": self.include_raw,
            "available_count": len(self.items),
            "missing_count": len(self.missing),
            "total_bytes": self.total_bytes,
            "sources": [
                {"name": name, "count": count}
                for name, count in sorted(source_counts.items(), key=lambda pair: pair[0].lower())
            ],
            "preview": [
                {
                    "asset_id": item.asset_id,
                    "source": item.source_name,
                    "relative_path": item.relative_path,
                    "destination_relative": item.destination_path.relative_to(self.destination).as_posix(),
                }
                for item in self.items[:20]
            ],
            "missing": list(self.missing[:50]),
        }


def _destination_root(value: str) -> Path:
    if not str(value or "").strip():
        raise ValueError("choose an existing destination folder")
    root = Path(str(value).strip()).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("destination folder must already exist")
    return root


def _validate_destination(destination: Path, source_roots: list[Path]) -> None:
    # Never allow an export to recurse into a registered source. This protects
    # both the user's originals and the next catalog scan.
    for source_root in source_roots:
        if _inside(destination, source_root):
            raise ValueError("destination cannot be inside a registered photo source")


def build_topic_copy_plan(
    connection: sqlite3.Connection,
    topic_id: str,
    *,
    destination_root: str,
    folder_name: str = "",
    include_raw: bool = True,
) -> TopicCopyPlan:
    """Build an exact, reviewable copy plan from topic membership.

    One topic membership produces at most one copy item. If an asset has more
    than one catalog location, the first currently available location is used.
    Missing/offline assets are returned as warnings instead of being silently
    dropped.
    """
    topic = connection.execute("SELECT name FROM events WHERE id=?", (topic_id,)).fetchone()
    if topic is None:
        raise ValueError("unknown topic")
    root = _destination_root(destination_root)
    destination = (root / _safe_component(folder_name or str(topic[0]), "topic")).resolve()

    rows = connection.execute(
        f"""SELECT ea.asset_id, al.volume_id, al.relative_path, al.filename,
                          al.size_bytes, al.missing_since, v.current_mount_path,
                          v.display_name, COALESCE(NULLIF(sp.source_id, ''), ''),
                          COALESCE(NULLIF(sp.display_name, ''), NULLIF(v.display_name, ''), v.id)
                   FROM event_assets ea
                   JOIN assets a ON a.id=ea.asset_id AND UPPER(a.media_type)='IMAGE'
                   LEFT JOIN asset_locations al ON al.asset_id=ea.asset_id
                   LEFT JOIN volumes v ON v.id=al.volume_id
                   LEFT JOIN source_profiles sp ON sp.source_id=al.source_id
                  WHERE ea.event_id=?
                  {'' if include_raw else f'AND al.missing_since IS NULL AND {visible_asset_sql("al")}'}
                  ORDER BY ea.asset_id, al.missing_since IS NOT NULL,
                           LOWER(COALESCE(v.display_name, '')), al.relative_path""",
        (topic_id,),
    ).fetchall()

    source_roots = [
        Path(str(row[0])).expanduser().resolve()
        for row in connection.execute(
            "SELECT current_mount_path FROM volumes WHERE current_mount_path IS NOT NULL"
        )
        if str(row[0]).strip()
    ]
    _validate_destination(destination, source_roots)

    rows_by_asset: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        rows_by_asset.setdefault(str(row[0]), []).append(row)
    memberships = [
        str(row[0])
        for row in connection.execute(
            """SELECT ea.asset_id
                 FROM event_assets ea JOIN assets a ON a.id=ea.asset_id
                WHERE ea.event_id=? AND UPPER(a.media_type)='IMAGE'
                ORDER BY ea.asset_id""",
            (topic_id,),
        )
    ]

    chosen: list[tuple[str, sqlite3.Row]] = []
    missing: list[dict[str, str]] = []
    source_identities: dict[tuple[str, str], str] = {}
    for asset_id in dict.fromkeys(memberships):
        candidates = rows_by_asset.get(asset_id, [])
        selected: sqlite3.Row | None = None
        for row in candidates:
            if not row[2] or not row[6]:
                continue
            try:
                relative = _safe_relative_path(str(row[2]))
                source_root = Path(str(row[6])).expanduser().resolve()
                source_path = (source_root / relative).resolve()
            except (OSError, ValueError):
                continue
            if _inside(source_path, source_root) and source_path.is_file():
                selected = row
                break
        if selected is None:
            filename = str(candidates[0][3] if candidates else "")
            missing.append({"asset_id": asset_id, "filename": filename, "reason": "source file is offline or missing"})
            continue
        source_key = (str(selected[8] or selected[1]), str(selected[9] or selected[1]))
        source_identities.setdefault(source_key, str(selected[9] or selected[1]))
        chosen.append((asset_id, selected))

    names = list(source_identities.values())
    duplicate_names = {name for name in names if names.count(name) > 1}
    source_components: dict[tuple[str, str], str] = {}
    for key, name in source_identities.items():
        component = _safe_component(name, "source")
        if name in duplicate_names:
            component = f"{component}-{_safe_component(key[0], 'source')[-16:]}"
        source_components[key] = component

    items: list[TopicCopyItem] = []
    for asset_id, row in chosen:
        relative = _safe_relative_path(str(row[2]))
        source_root = Path(str(row[6])).expanduser().resolve()
        source_path = (source_root / relative).resolve()
        source_key = (str(row[8] or row[1]), str(row[9] or row[1]))
        source_name = str(row[9] or row[1])
        target = (destination / source_components[source_key] / relative).resolve()
        if not _inside(target, destination):
            raise ValueError("catalog path would escape the destination folder")
        items.append(TopicCopyItem(
            asset_id=asset_id,
            filename=str(row[3] or relative.name),
            source_id=str(row[8] or row[1]),
            source_name=source_name,
            source_root=source_root,
            source_path=source_path,
            relative_path=relative.as_posix(),
            destination_path=target,
            size_bytes=int(row[4] or source_path.stat().st_size),
        ))
    items.sort(key=lambda item: (item.source_name.lower(), item.relative_path.lower(), item.asset_id))
    return TopicCopyPlan(str(topic_id), str(topic[0]), destination, bool(include_raw), tuple(items), tuple(missing))


def _copy_exclusive(source: Path, destination: Path) -> None:
    """Copy without replacing a file created by another process mid-copy."""
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as stream, source.open("rb") as source_stream:
            shutil.copyfileobj(source_stream, stream, length=1024 * 1024)
        try:
            shutil.copystat(source, destination)
        except OSError:
            pass
    except Exception:
        try:
            destination.unlink()
        except OSError:
            pass
        raise


def execute_topic_copy(plan: TopicCopyPlan) -> dict[str, object]:
    """Copy and verify every available item; never overwrite conflicts."""
    copied = already_present = verified = failed = conflicts = 0
    errors: list[dict[str, str]] = []
    for item in plan.items:
        try:
            if not item.source_path.is_file() or not _inside(item.source_path.resolve(), item.source_root):
                raise OSError("source file is no longer available")
            source_hash = sha256_file(item.source_path)
            if item.destination_path.exists():
                if item.destination_path.is_file() and sha256_file(item.destination_path) == source_hash:
                    already_present += 1
                    verified += 1
                    continue
                conflicts += 1
                errors.append({"asset_id": item.asset_id, "path": str(item.destination_path), "reason": "destination exists with different content"})
                continue
            item.destination_path.parent.mkdir(parents=True, exist_ok=True)
            _copy_exclusive(item.source_path, item.destination_path)
            copied += 1
            if sha256_file(item.destination_path) != source_hash:
                item.destination_path.unlink(missing_ok=True)
                raise OSError("destination verification failed")
            verified += 1
        except (OSError, ValueError) as exc:
            failed += 1
            errors.append({"asset_id": item.asset_id, "path": str(item.source_path), "reason": str(exc)})

    total = len(plan.items) + len(plan.missing)
    complete = failed == 0 and conflicts == 0 and not plan.missing
    status = "COMPLETED" if complete else ("PARTIAL" if verified else "FAILED")
    return {
        "ok": status in {"COMPLETED", "PARTIAL"},
        "status": status,
        "destination": str(plan.destination),
        "total": total,
        "copied": copied,
        "already_present": already_present,
        "verified": verified,
        "missing": len(plan.missing),
        "conflicts": conflicts,
        "failed": failed,
        "errors": [*list(plan.missing[:50]), *errors[:50]],
    }
