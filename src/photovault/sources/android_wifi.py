"""Read-only client for the PhotoVault Android Companion POC."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import BinaryIO, Iterable, Iterator
from urllib.parse import urlencode
from urllib.error import HTTPError
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


@dataclass(frozen=True)
class AndroidEmbeddedLocation:
    """Coordinates directly read by the Companion from an original media file."""

    latitude: float
    longitude: float
    source: str


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
    session_token: str | None = None
    expected_android_fingerprint: str | None = None
    _identity_cache: SourceIdentity | None = field(default=None, init=False, repr=False)
    _pending_pairings: dict[str, tuple[str, bytes]] = field(default_factory=dict, init=False, repr=False)
    _pairing_results: dict[str, dict[str, str]] = field(default_factory=dict, init=False, repr=False)
    _handshake_hash: bytes | None = field(default=None, init=False, repr=False)

    def _request(self, path: str, *, headers: dict[str, str] | None = None, params: dict[str, object] | None = None, _retried: bool = False):
        request_headers = dict(headers or {})
        if self.session_token:
            request_headers["Authorization"] = f"Bearer {self.session_token}"
        query_params = dict(params or {})
        if not self.session_token:
            query_params["token"] = self.token
        query = urlencode(query_params)
        separator = "&" if "?" in path else "?"
        url = f"{self.base_url.rstrip('/')}{path}{separator}{query}"
        try:
            return urlopen(Request(url, headers=request_headers), timeout=self.timeout)
        except HTTPError as exc:
            if exc.code == 401 and self.session_token and self.expected_android_fingerprint and not _retried:
                self.reconnect(expected_android_fingerprint=self.expected_android_fingerprint)
                return self._request(path, headers=headers, params=params, _retried=True)
            raise AndroidCompanionUnavailable(f"companion request failed: HTTP {exc.code}") from exc
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

    def _post_json(self, path: str, payload: dict[str, object]) -> dict:
        url = f"{self.base_url.rstrip('/')}{path}"
        request = Request(url, data=json.dumps(payload, separators=(",", ":")).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            try:
                error_payload = json.load(exc)
            except (ValueError, OSError):
                error_payload = {}
            detail = error_payload.get("error") if isinstance(error_payload, dict) else None
            message = str(detail or f"companion pairing failed: HTTP {exc.code}")
            raise AndroidCompanionUnavailable(message) from exc
        except OSError as exc:
            raise AndroidCompanionUnavailable(str(exc)) from exc
        if not result.get("ok"):
            raise AndroidCompanionUnavailable(str(result.get("error", "companion pairing failed")))
        return result

    def pair(self, *, desktop_name: str = "Photo Manager") -> dict[str, str]:
        """Perform the Noise XX handshake; UI confirmation remains two-sided.

        This intentionally does not send the legacy bearer token. The caller
        must display ``sas`` and collect explicit confirmation from both peers
        before persisting a trusted device.
        """
        try:
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from noise.connection import Keypair, NoiseConnection
        except ImportError as exc:
            raise AndroidCompanionUnavailable("install the pairing optional dependencies") from exc
        started = self._post_json("/api/pair/start", {"desktop_name": desktop_name, "protocol": "photovault-pairing-v1"})
        session_id = str(started.get("session_id", ""))
        if not session_id: raise AndroidCompanionUnavailable("companion returned no pairing session")
        device_id = str(started.get("device_id", ""))
        private_key, store = self._desktop_private_key(X25519PrivateKey)
        initiator = NoiseConnection.from_name(b"Noise_XX_25519_ChaChaPoly_SHA256")
        initiator.set_as_initiator(); initiator.set_prologue(b"photovault-pairing-v1")
        initiator.set_keypair_from_private_bytes(Keypair.STATIC, private_key); initiator.start_handshake()
        first = bytes(initiator.write_message())
        second_payload = self._post_json(f"/api/pair/{session_id}/message", {"message": base64.b64encode(first).decode()})
        second = base64.b64decode(str(second_payload.get("message", "")))
        initiator.read_message(second)
        third = bytes(initiator.write_message())
        final = self._post_json(f"/api/pair/{session_id}/message", {"message": base64.b64encode(third).decode()})
        self._handshake_hash = initiator.get_handshake_hash()
        self.expected_android_fingerprint = str(final.get("fingerprint") or "") or None
        pending_ref = f"pairing-pending:{device_id}:{session_id}"
        store.put(pending_ref, base64.b64encode(private_key))
        self._pending_pairings[session_id] = (pending_ref, private_key)
        result = {"session_id": session_id, "device_id": device_id, "display_name": str(started.get("display_name", "Android device")), "sas": str(final.get("sas", "")), "fingerprint": str(final.get("fingerprint", "")), "state": "AWAITING_NUMERIC_CONFIRMATION"}
        self._pairing_results[session_id] = result
        return result

    def confirm_pairing(self, session_id: str) -> bool:
        """Confirm the desktop side after the user compared both SAS values."""
        result = self._post_json(f"/api/pair/{session_id}/confirm", {})
        if result.get("paired"):
            from photovault.pairing.protocol import transfer_session_token
            self.session_token = transfer_session_token(self._handshake_hash or b"")
            pending = self._pending_pairings.pop(session_id, None)
            if pending:
                pending_ref, private_key = pending
                from photovault.pairing.credentials import KeyringCredentialStore
                store = KeyringCredentialStore()
                store.put("desktop-noise-static-v1", base64.b64encode(private_key if isinstance(private_key, bytes) else bytes(private_key)))
                store.delete(pending_ref)
            return True
        return False

    def pairing_result(self, session_id: str) -> dict[str, str]:
        try: return dict(self._pairing_results[session_id])
        except KeyError as exc: raise AndroidCompanionUnavailable("unknown pairing session") from exc

    def reconnect(self, *, expected_android_fingerprint: str) -> dict[str, str]:
        """Reconnect without SAS and require the previously pinned Android key."""
        try:
            from noise.connection import Keypair, NoiseConnection
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        except ImportError as exc: raise AndroidCompanionUnavailable("install the pairing optional dependencies") from exc
        started = self._post_json("/api/reconnect/start", {})
        session_id = str(started.get("session_id", ""))
        private_key, _ = self._desktop_private_key(X25519PrivateKey, create=False)
        initiator = NoiseConnection.from_name(b"Noise_XX_25519_ChaChaPoly_SHA256")
        initiator.set_as_initiator(); initiator.set_prologue(b"photovault-pairing-v1")
        initiator.set_keypair_from_private_bytes(Keypair.STATIC, private_key); initiator.start_handshake()
        first = bytes(initiator.write_message())
        second_payload = self._post_json(f"/api/reconnect/{session_id}/message", {"message": base64.b64encode(first).decode()})
        initiator.read_message(base64.b64decode(str(second_payload.get("message", ""))))
        final = self._post_json(f"/api/reconnect/{session_id}/message", {"message": base64.b64encode(bytes(initiator.write_message())).decode()})
        fingerprint = str(final.get("fingerprint", ""))
        if not final.get("authenticated") or fingerprint != expected_android_fingerprint:
            raise AndroidCompanionUnavailable("Android security identity changed or is not trusted")
        from photovault.pairing.protocol import transfer_session_token
        self._handshake_hash = initiator.get_handshake_hash()
        self.expected_android_fingerprint = expected_android_fingerprint
        self.session_token = transfer_session_token(self._handshake_hash)
        return {"device_id": str(started.get("device_id", "")), "fingerprint": fingerprint, "state": "CONNECTED"}

    @staticmethod
    def _desktop_private_key(key_type, *, create: bool = True):
        from photovault.pairing.credentials import KeyringCredentialStore
        store = KeyringCredentialStore(); reference = "desktop-noise-static-v1"; stored = store.get(reference)
        if stored is None and not create: raise AndroidCompanionUnavailable("no trusted desktop credential exists")
        private_key = base64.b64decode(stored) if stored else key_type.generate().private_bytes_raw()
        if stored is None: store.put(reference, base64.b64encode(private_key))
        return private_key, store

    def identity(self) -> SourceIdentity:
        if self._identity_cache is not None:
            return self._identity_cache
        device = self.device_details()
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

    def device_details(self) -> dict[str, object]:
        """Return the Companion's read-only manifest for a desktop connection view."""
        device = self._json("/api/device").get("device")
        if not isinstance(device, dict):
            raise AndroidCompanionUnavailable("invalid Companion device manifest")
        return device

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
        return frozenset({"identity", "media_manifest", "stream_object", "range_read", "embedded_metadata"})

    def embedded_location(self, object_id: str) -> AndroidEmbeddedLocation | None:
        """Read original-file GPS on demand; never infer it from MediaStore or Photos."""
        location = self._json(f"/api/media/{object_id}/metadata").get("location")
        if location is None:
            return None
        if not isinstance(location, dict):
            raise AndroidCompanionUnavailable("invalid embedded location response")
        try:
            latitude, longitude = float(location["latitude"]), float(location["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AndroidCompanionUnavailable("invalid embedded location coordinates") from exc
        source = str(location.get("source") or "")
        if source not in {"embedded_exif", "embedded_video_metadata"} or not (math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise AndroidCompanionUnavailable("invalid embedded location provenance")
        return AndroidEmbeddedLocation(latitude, longitude, source)

    def stream_object(self, object_id: str, sink: BinaryIO, *, offset: int = 0) -> dict[str, int | float]:
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        started = time.monotonic(); received = 0
        with self._request(f"/api/media/{object_id}", headers=headers) as response:
            while chunk := response.read(256 * 1024):
                sink.write(chunk); received += len(chunk)
        elapsed = time.monotonic() - started
        return {"bytes_received": received, "elapsed_seconds": elapsed, "bytes_per_second": received / elapsed if elapsed else 0.0}
