from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from photovault.sources.base import PhotoSource


@dataclass(frozen=True)
class SourceImportItem:
    object_id: str
    relative_path: str
    size_bytes: int | None
    expected_sha256: str | None = None


def _safe_destination(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("source path escapes destination root")
    return candidate


def stream_source_to_file(
    source: PhotoSource,
    item: SourceImportItem,
    destination_root: Path,
) -> dict[str, int | float | str]:
    """Stream one source object through bounded memory into an atomic destination."""
    destination = _safe_destination(destination_root, item.relative_path)
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".photomanager-partial")
    if partial.exists():
        raise FileExistsError(f"stale partial destination exists: {partial}")

    digest = hashlib.sha256()
    bytes_written = 0
    started = time.monotonic()
    try:
        with partial.open("xb") as output:
            class HashingSink:
                def write(self, data: bytes) -> int:
                    nonlocal bytes_written
                    digest.update(data)
                    bytes_written += len(data)
                    return output.write(data)

            metrics = source.stream_object(item.object_id, HashingSink())
            output.flush()
            os.fsync(output.fileno())
        actual_hash = digest.hexdigest()
        if item.size_bytes is not None and bytes_written != item.size_bytes:
            raise ValueError(f"source size mismatch: expected {item.size_bytes}, got {bytes_written}")
        if item.expected_sha256 is not None and actual_hash != item.expected_sha256:
            raise ValueError(f"source SHA-256 mismatch: expected {item.expected_sha256}, got {actual_hash}")
        if destination.exists():
            raise FileExistsError(f"destination appeared during import: {destination}")
        os.replace(partial, destination)
        return {
            "object_id": item.object_id,
            "destination": str(destination),
            "bytes_written": bytes_written,
            "sha256": actual_hash,
            "elapsed_seconds": time.monotonic() - started,
            "source_bytes_per_second": metrics.get("bytes_per_second", 0.0),
        }
    except Exception:
        if partial.exists():
            partial.unlink()
        raise
