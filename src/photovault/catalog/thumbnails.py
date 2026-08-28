from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


THUMBNAIL_VERSION = "v1-320"


def generate_thumbnail(connection, asset_id: str, source: Path, cache_root: Path, size: int = 320) -> Path | None:
    if Image is None or source.suffix.lower() in {".mov", ".mp4", ".m4v", ".avi"}:
        return None
    destination = cache_root.expanduser().resolve() / f"{asset_id}_{THUMBNAIL_VERSION}.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not destination.exists():
            with Image.open(source) as image:
                image = image.convert("RGB")
                image.thumbnail((size, size), Image.Resampling.LANCZOS)
                image.save(destination, format="JPEG", quality=84, optimize=True)
        with Image.open(destination) as thumb:
            width, height = thumb.size
        connection.execute(
            "INSERT INTO thumbnails(asset_id, version, path, width, height, created_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(asset_id, version) DO UPDATE SET path=excluded.path, width=excluded.width, height=excluded.height",
            (asset_id, THUMBNAIL_VERSION, str(destination), width, height, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        return destination
    except (OSError, ValueError):
        return None
