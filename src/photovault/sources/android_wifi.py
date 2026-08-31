"""Read-only client for the PhotoVault Android Companion POC."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import BinaryIO, Iterable, Iterator
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import PhotoItem, PhotoSource, SourceIdentity, SourceStorage


class AndroidCompanionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class AndroidMediaFolder:
    relative_path: str
    count: int
    image_count: int
    video_count: int
    size_bytes: int


def _when_millis(value: object) -> datetime | None:
    try:
        number = int(value)
        # MediaStore DATE_TAKEN is milliseconds; DATE_MODIFIED is seconds.
        seconds = number / 1000 if number > 10_000_000_000 else number
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


@dataclass
class AndroidCompanionWifiSource(PhotoSource):
    base_url: str
    token: str
    timeout: float = 30.0
    _identity_cache: SourceIdentity | None = field(default=None, init=False, repr=False)

    def _request(self, path: str, *, headers: dict[str, str] | None = None, params: dict[str, object] | None = None):
        query = urlencode({"token": self.token, **(params or {})})
        separator = "&" if "?" in path else "?"
        url = f"{self.base_url.rstrip('/')}{path}{separator}{query}"
        try:
            return urlopen(Request(url, headers=headers or {}), timeout=self.timeout)
        except OSError as exc:
            raise AndroidCompanionUnavailable(str(exc)) from exc

    def _json(self, path: str, *, params: dict[str, object] | None = None) -> dict:
        with self._request(path, params=params) as response:
            try:
                payload = json.load(response)
            except (ValueError, OSError) as exc:
                raise AndroidCompanionUnavailable(f"invalid companion response: {exc}") from exc
        if not payload.get("ok"):
            raise AndroidCompanionUnavailable(payload.get("error", "companion request failed"))
        return payload

    def identity(self) -> SourceIdentity:
        if self._identity_cache is not None:
            return self._identity_cache
        device = self._json("/api/device")["device"]
        persistent_id = str(device.get("device_id") or "").strip()
        # New Companions expose an installation UUID that survives IP changes.
        # Keep the legacy endpoint fallback for old APKs, but distinguish it
        # because that fallback cannot provide incremental-backup continuity.
        fingerprint_input = persistent_id or f"legacy|{device.get('manufacturer')}|{device.get('model')}|{self.base_url}"
        fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()[:24]
        self._identity_cache = SourceIdentity(
            source_id=f"android_wifi_{fingerprint}",
            manufacturer=device.get("manufacturer", "Android"),
            model=device.get("model", "Android device"),
            display_name=device.get("friendly_name") or device.get("model", "Android device"),
            adapter="android_companion_wifi",
        )
        return self._identity_cache

    def list_storages(self) -> Iterable[SourceStorage]:
        yield SourceStorage(1, "Android MediaStore")

    def _item(self, row: dict) -> PhotoItem:
        mime = row.get("mime_type", "")
        return PhotoItem(
            source_id=self.identity().source_id,
            object_id=str(row["object_id"]),
            parent_id=None,
            name=row.get("name", "untitled"),
            media_type="VIDEO" if mime.startswith("video/") else "IMAGE",
            size_bytes=row.get("size_bytes"),
            created_at=_when_millis(row.get("date_taken")),
            modified_at=_when_millis(row.get("modified_at", 0)) if row.get("modified_at", 0) else None,
        )

    def list_children(self, parent_id: str | None) -> Iterable[PhotoItem]:
        if parent_id is not None:
            return iter(())
        return iter([self._item(row) for row in self._json("/api/media").get("items", [])])

    def folders(self) -> list[AndroidMediaFolder]:
        rows = self._json("/api/folders").get("folders", [])
        return [AndroidMediaFolder(
            relative_path=str(row["relative_path"]), count=int(row["count"]),
            image_count=int(row.get("images", 0)), video_count=int(row.get("videos", 0)),
            size_bytes=int(row.get("size_bytes", 0)),
        ) for row in rows]

    def folder_count(self, relative_path: str) -> int:
        return int(self._json("/api/media/count", params={"relative_path": relative_path})["count"])

    def list_folder_page(self, relative_path: str, *, offset: int = 0, limit: int = 500, oldest_first: bool = False) -> list[PhotoItem]:
        params: dict[str, object] = {"relative_path": relative_path, "offset": offset, "limit": min(500, max(1, limit))}
        if oldest_first:
            params["sort"] = "oldest"
        rows = self._json("/api/media", params=params).get("items", [])
        return [self._item(row) for row in rows]

    def iter_folder(self, relative_path: str, *, page_size: int = 500, oldest_first: bool = False) -> Iterator[PhotoItem]:
        offset = 0
        while True:
            page = self.list_folder_page(relative_path, offset=offset, limit=page_size, oldest_first=oldest_first)
            yield from page
            if len(page) < page_size:
                return
            offset += len(page)

    def stat_item(self, object_id: str) -> PhotoItem:
        for item in self.list_children(None):
            if item.object_id == str(object_id):
                return item
        raise AndroidCompanionUnavailable(f"media object not present in companion manifest: {object_id}")

    def capabilities(self) -> frozenset[str]:
        return frozenset({"identity", "media_manifest", "stream_object", "range_read"})

    def stream_object(self, object_id: str, sink: BinaryIO, *, offset: int = 0) -> dict[str, int | float]:
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        started = time.monotonic(); received = 0
        with self._request(f"/api/media/{object_id}", headers=headers) as response:
            while chunk := response.read(256 * 1024):
                sink.write(chunk); received += len(chunk)
        elapsed = time.monotonic() - started
        return {"bytes_received": received, "elapsed_seconds": elapsed, "bytes_per_second": received / elapsed if elapsed else 0.0}
