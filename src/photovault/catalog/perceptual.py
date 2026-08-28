from __future__ import annotations

import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional photo feature
    Image = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pack(bits: list[bool]) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def dhash64(path: Path, hash_size: int = 8) -> int:
    """Return the 64-bit difference hash for an image."""
    if Image is None:
        raise RuntimeError("Pillow is required for perceptual hashing")
    with Image.open(path) as image:
        image = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
        pixels = list(image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata())
    return _pack(pixels[row * (hash_size + 1) + col] > pixels[row * (hash_size + 1) + col + 1]
                 for row in range(hash_size) for col in range(hash_size))


def phash64(path: Path, hash_size: int = 32, low_frequency_size: int = 8) -> int:
    """Return a compact 64-bit DCT perceptual hash without a scipy dependency."""
    if Image is None:
        raise RuntimeError("Pillow is required for perceptual hashing")
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - optional photo feature
        raise RuntimeError("numpy is required for pHash") from exc
    with Image.open(path) as image:
        pixels = np.asarray(image.convert("L").resize((hash_size, hash_size), Image.Resampling.LANCZOS), dtype=float)
    n = hash_size
    x = np.arange(n)
    basis = np.cos(math.pi / n * (x + 0.5)[:, None] * np.arange(n)[None, :])
    basis[:, 0] *= 1 / math.sqrt(2)
    coeff = (2 / n) * basis.T @ pixels @ basis
    low = coeff[:low_frequency_size, :low_frequency_size].flatten()
    values = low[1:]
    median = float(np.median(values))
    # Exclude DC from the threshold calculation, but retain it as the first
    # bit so the persisted representation remains exactly 64-bit.
    return _pack([float(low[0]) > median] + [float(value) > median for value in values[:63]])


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


class BKTree:
    """BK-tree for metric queries, avoiding an all-pairs similarity scan."""

    def __init__(self) -> None:
        self._root: tuple[int, object] | None = None
        self._children: dict[int, dict[int, tuple[int, object]]] = {}

    def add(self, value: int, item: object) -> None:
        if self._root is None:
            self._root = (value, item)
            self._children[id(self._root)] = {}
            return
        node = self._root
        while True:
            distance = hamming_distance(value, node[0])
            children = self._children.setdefault(id(node), {})
            if distance == 0:
                return
            if distance not in children:
                child = (value, item)
                children[distance] = child
                self._children[id(child)] = {}
                return
            node = children[distance]

    def query(self, value: int, maximum_distance: int) -> list[tuple[int, object]]:
        if self._root is None:
            return []
        matches: list[tuple[int, object]] = []
        pending = [self._root]
        while pending:
            node = pending.pop()
            distance = hamming_distance(value, node[0])
            if distance <= maximum_distance:
                matches.append((distance, node[1]))
            children = self._children.get(id(node), {})
            for edge, child in children.items():
                if distance - maximum_distance <= edge <= distance + maximum_distance:
                    pending.append(child)
        return matches


def _locations(connection: sqlite3.Connection, volume_id: str | None) -> list[sqlite3.Row]:
    where = "WHERE al.missing_since IS NULL AND v.status='CONNECTED' AND v.current_mount_path IS NOT NULL"
    params: tuple[object, ...] = ()
    if volume_id:
        where += " AND v.id=?"
        params = (volume_id,)
    return list(connection.execute(
        "SELECT al.asset_id, v.current_mount_path, al.relative_path "
        "FROM asset_locations al JOIN volumes v ON v.id=al.volume_id " + where +
        " ORDER BY al.asset_id, v.status DESC, al.id", params
    ))


def index_perceptual_hashes(
    connection: sqlite3.Connection,
    volume_id: str | None = None,
    algorithms: tuple[str, ...] = ("dhash64", "phash64"),
    limit: int = 0,
) -> dict[str, int]:
    rows = _locations(connection, volume_id)
    representatives: dict[str, Path] = {}
    for row in rows:
        representatives.setdefault(row[0], Path(row[1]) / row[2])
    if limit > 0:
        representatives = dict(list(representatives.items())[:limit])
    counts = {algorithm: 0 for algorithm in algorithms}
    errors = 0
    for asset_id, path in representatives.items():
        for algorithm in algorithms:
            try:
                value = dhash64(path) if algorithm == "dhash64" else phash64(path)
                connection.execute(
                    "INSERT INTO perceptual_hashes(asset_id, algorithm, hash_value, computed_at) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(asset_id, algorithm) DO UPDATE SET "
                    "hash_value=excluded.hash_value, computed_at=excluded.computed_at",
                    (asset_id, algorithm, f"{value:016x}", _now()),
                )
                counts[algorithm] += 1
            except (OSError, RuntimeError, ValueError):
                errors += 1
    connection.commit()
    counts["errors"] = errors
    counts["assets"] = len(representatives)
    return counts


def find_visual_duplicate_groups(
    connection: sqlite3.Connection,
    algorithm: str = "phash64",
    threshold: int = 8,
    volume_id: str | None = None,
) -> list[dict[str, object]]:
    if algorithm not in {"dhash64", "phash64"}:
        raise ValueError("algorithm must be dhash64 or phash64")
    if threshold < 0 or threshold > 64:
        raise ValueError("threshold must be between 0 and 64")
    params: tuple[object, ...] = (algorithm,)
    sql = "SELECT DISTINCT ph.asset_id, ph.hash_value FROM perceptual_hashes ph " \
          "JOIN asset_locations al ON al.asset_id=ph.asset_id " \
          "WHERE ph.algorithm=? AND al.missing_since IS NULL"
    if volume_id:
        sql += " AND al.volume_id=?"
        params = (algorithm, volume_id)
    rows = list(connection.execute(sql, params))
    tree = BKTree()
    parent: dict[str, str] = {}

    def find(asset: str) -> str:
        parent.setdefault(asset, asset)
        while parent[asset] != asset:
            parent[asset] = parent[parent[asset]]
            asset = parent[asset]
        return asset

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    distances: dict[tuple[str, str], int] = {}
    for row in rows:
        asset_id, value = row[0], int(row[1], 16)
        parent.setdefault(asset_id, asset_id)
        for distance, other in tree.query(value, threshold):
            if other != asset_id:
                pair = tuple(sorted((asset_id, str(other))))
                distances[pair] = min(distance, distances.get(pair, 64))
                union(*pair)
        tree.add(value, asset_id)

    groups: dict[str, set[str]] = {}
    for asset in parent:
        root = find(asset)
        groups.setdefault(root, set()).add(asset)
    connection.execute("DELETE FROM duplicate_groups WHERE algorithm=? AND threshold=?", (algorithm, threshold))
    result: list[dict[str, object]] = []
    group_type = "REENCODED_COPY" if threshold <= 4 else "NEAR_DUPLICATE"
    for assets in groups.values():
        if len(assets) < 2:
            continue
        group_id = "dup_" + uuid.uuid4().hex
        connection.execute(
            "INSERT INTO duplicate_groups(id, group_type, algorithm, threshold, created_at) VALUES (?, ?, ?, ?, ?)",
            (group_id, group_type, algorithm, threshold, _now()),
        )
        members = []
        for asset in sorted(assets):
            distance = min((distance for (left, right), distance in distances.items()
                            if asset in (left, right)), default=0)
            connection.execute(
                "INSERT INTO duplicate_group_members(group_id, asset_id, distance) VALUES (?, ?, ?)",
                (group_id, asset, distance),
            )
            members.append({"asset_id": asset, "distance": distance})
        result.append({"id": group_id, "group_type": group_type, "algorithm": algorithm,
                       "threshold": threshold, "members": members})
    connection.commit()
    return result
