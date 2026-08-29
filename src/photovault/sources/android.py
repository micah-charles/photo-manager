from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Iterable

from .base import PhotoItem, PhotoSource, SourceIdentity, SourceStorage


class AndroidSourceUnavailable(RuntimeError):
    """Raised when the optional native Android adapter cannot be used."""


class JsonLineBridge:
    """Small request/response bridge; media bytes never travel through JSON."""

    def __init__(self, command: list[str], runner=subprocess.Popen) -> None:
        self._closed = False
        self._process = runner(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def request(self, operation: str, **arguments: Any) -> dict[str, Any]:
        if self._closed:
            raise AndroidSourceUnavailable("native helper is closed")
        if self._process.stdin is None or self._process.stdout is None:
            raise AndroidSourceUnavailable("native helper pipes are unavailable")
        self._process.stdin.write(json.dumps({"operation": operation, **arguments}) + "\n")
        self._process.stdin.flush()
        line = self._process.stdout.readline()
        if not line:
            stderr = ""
            if self._process.poll() is not None and self._process.stderr is not None:
                stderr = self._process.stderr.read().strip()
            detail = f": {stderr}" if stderr else ""
            raise AndroidSourceUnavailable(f"native helper exited without a response{detail}")
        response = json.loads(line)
        if not response.get("ok", False):
            detail = response.get("error", "native helper request failed")
            raise AndroidSourceUnavailable(f"{operation}: {detail}")
        return response

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process.stdin:
            self._process.stdin.close()
        if self._process.poll() is None:
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                self._process.wait(timeout=5)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S")
    except ValueError:
        return None


def _media_type(format_code: int, name: str) -> str:
    if format_code == 0x3001:
        return "COLLECTION"
    suffix = Path(name).suffix.lower()
    return "VIDEO" if suffix in {".mp4", ".mov", ".m4v", ".avi"} else "IMAGE"


@dataclass
class AndroidMacMtpSource(PhotoSource):
    bridge: JsonLineBridge
    _identity: SourceIdentity
    helper: Path | None = None

    @classmethod
    def from_helper(cls, helper: Path) -> "AndroidMacMtpSource":
        if platform.system() != "Darwin":
            raise AndroidSourceUnavailable("Android MTP is unavailable on this platform")
        if not helper.exists():
            raise AndroidSourceUnavailable(f"native helper not found: {helper}")
        bridge = JsonLineBridge([str(helper)])
        try:
            response = bridge.request("open_device")
        except Exception:
            bridge.close()
            raise
        device = response["device"]
        serial_fingerprint = device.get("serial_fingerprint", "")
        source_id = "android_" + hashlib.sha256(
            f"{device.get('manufacturer','')}|{device.get('model','')}|{device.get('vid')}|{device.get('pid')}|{serial_fingerprint}".encode()
        ).hexdigest()[:24]
        identity = SourceIdentity(
            source_id=source_id,
            manufacturer=device.get("manufacturer", ""),
            model=device.get("model", ""),
            display_name=device.get("friendly_name") or device.get("model", "Android device"),
            adapter="macos_iousbhost_mtp",
            usb_vendor_id=device.get("vid"),
            usb_product_id=device.get("pid"),
        )
        return cls(bridge, identity, helper)

    def identity(self) -> SourceIdentity:
        return self._identity

    def list_storages(self) -> Iterable[SourceStorage]:
        for storage in self.bridge.request("list_storages").get("storages", []):
            yield SourceStorage(storage["storage_id"], storage.get("name", "Internal storage"), storage.get("capacity_bytes"), storage.get("free_bytes"))

    def list_children(self, parent_id: str | None) -> Iterable[PhotoItem]:
        list(self.list_storages())
        parent = None if parent_id is None else int(parent_id)
        for item in self.bridge.request("list_children", parent_id=parent).get("items", []):
            yield self._item(item)

    def stat_item(self, object_id: str) -> PhotoItem:
        return self._item(self.bridge.request("object_info", object_id=int(object_id))["item"])

    def capabilities(self) -> frozenset[str]:
        return frozenset({"identity", "list_storages", "list_children", "stat_item", "stream_object"})

    def stream_object(self, object_id: str, sink: BinaryIO) -> dict[str, int | float]:
        if self.helper is None:
            raise AndroidSourceUnavailable("stream helper path is unavailable")
        list(self.list_storages())
        self.close()
        started = time.monotonic()
        process = subprocess.Popen(
            [str(self.helper), "--stream", str(int(object_id))],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        bytes_received = 0
        try:
            if process.stdout is None:
                raise AndroidSourceUnavailable("native stream stdout is unavailable")
            while chunk := process.stdout.read(256 * 1024):
                sink.write(chunk)
                bytes_received += len(chunk)
        finally:
            process.stdout.close() if process.stdout else None
        stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
        return_code = process.wait(timeout=30)
        if return_code != 0:
            raise AndroidSourceUnavailable(stderr.strip() or f"native stream exited with {return_code}")
        elapsed = time.monotonic() - started
        return {
            "bytes_received": bytes_received,
            "elapsed_seconds": elapsed,
            "bytes_per_second": bytes_received / elapsed if elapsed else 0.0,
        }

    def close(self) -> None:
        try:
            self.bridge.request("close_device")
        except (AndroidSourceUnavailable, OSError, ValueError):
            pass
        finally:
            self.bridge.close()

    def _item(self, item: dict[str, Any]) -> PhotoItem:
        return PhotoItem(
            source_id=self._identity.source_id,
            object_id=str(item["object_id"]),
            parent_id=None if item.get("parent_id") is None else str(item["parent_id"]),
            name=item["name"],
            media_type=_media_type(item.get("format", 0), item["name"]),
            size_bytes=item.get("size_bytes"),
            created_at=_parse_datetime(item.get("created_at")),
            modified_at=_parse_datetime(item.get("modified_at")),
            is_collection=item.get("format") == 0x3001,
        )
