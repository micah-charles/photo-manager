"""Pairing v2 protocol primitives shared by the desktop service and tests.

This module intentionally contains no transport code.  TLS and certificate
verification are layered on top of these deterministic, interoperable rules.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum


PAIRING_V2_PROTOCOL = "photovault-pairing-v2"


class AndroidPairingState(StrEnum):
    IDLE = "IDLE"
    PAIRING_AVAILABLE = "PAIRING_AVAILABLE"
    PAIR_REQUEST_RECEIVED = "PAIR_REQUEST_RECEIVED"
    AWAITING_ANDROID_CONFIRMATION = "AWAITING_ANDROID_CONFIRMATION"
    ANDROID_CONFIRMED = "ANDROID_CONFIRMED"
    AWAITING_DESKTOP_CONFIRMATION = "AWAITING_DESKTOP_CONFIRMATION"
    PAIRED = "PAIRED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class DesktopPairingState(StrEnum):
    NOT_DISCOVERED = "NOT_DISCOVERED"
    DISCOVERED = "DISCOVERED"
    UNREACHABLE = "UNREACHABLE"
    REACHABLE = "REACHABLE"
    UNPAIRED = "UNPAIRED"
    PAIRING_PENDING = "PAIRING_PENDING"
    AWAITING_ANDROID_CONFIRMATION = "AWAITING_ANDROID_CONFIRMATION"
    AWAITING_DESKTOP_CONFIRMATION = "AWAITING_DESKTOP_CONFIRMATION"
    TRUSTED = "TRUSTED"
    CONNECTED = "CONNECTED"
    OFFLINE = "OFFLINE"
    PAIRING_EXPIRED = "PAIRING_EXPIRED"
    PAIRING_REJECTED = "PAIRING_REJECTED"
    IDENTITY_CHANGED = "IDENTITY_CHANGED"
    REVOKED = "REVOKED"
    ERROR = "ERROR"


def _field(value: str) -> bytes:
    """Encode one SAS field with an unambiguous length prefix."""
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(4, "big") + encoded


def pairing_v2_digest(*, android_fingerprint: str, desktop_fingerprint: str,
                      nonce: bytes) -> bytes:
    """Return the exact digest input defined by Pairing v2.

    Fields are UTF-8, length-prefixed, and ordered protocol/android/desktop/
    nonce.  The nonce is length-prefixed as raw bytes.  This avoids implicit
    Java/Python integer or delimiter behaviour.
    """
    protocol = _field(PAIRING_V2_PROTOCOL)
    android = _field(android_fingerprint)
    desktop = _field(desktop_fingerprint)
    nonce_field = len(nonce).to_bytes(4, "big") + nonce
    return hashlib.sha256(protocol + android + desktop + nonce_field).digest()


def pairing_v2_sas(*, android_fingerprint: str, desktop_fingerprint: str,
                  nonce: bytes) -> str:
    """Derive a six-digit unsigned numeric comparison value."""
    digest = pairing_v2_digest(
        android_fingerprint=android_fingerprint,
        desktop_fingerprint=desktop_fingerprint,
        nonce=nonce,
    )
    number = int.from_bytes(digest[:8], "big", signed=False) % 1_000_000
    return f"{number:06d}"


@dataclass(frozen=True)
class PairingRequest:
    pair_request_id: str
    device_id: str
    display_name: str
    remote_address: str
    android_certificate_fingerprint: str
    desktop_certificate_fingerprint: str
    pairing_nonce: bytes
    sas: str
    state: str
    android_confirmed: bool
    desktop_confirmed: bool
    created_at: str
    expires_at: str
    updated_at: str
    failure_reason: str | None = None


class PairingRequestStore:
    """SQLite persistence for v2 pairing state; secrets stay out of SQLite."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(self, *, pair_request_id: str, device_id: str, display_name: str,
               remote_address: str, android_certificate_fingerprint: str,
               desktop_certificate_fingerprint: str, pairing_nonce: bytes,
               sas: str, ttl_seconds: int = 120) -> PairingRequest:
        now = datetime.now(timezone.utc)
        created = now.isoformat(timespec="seconds")
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")
        self.connection.execute(
            """INSERT INTO android_pairing_requests_v2(
                pair_request_id, device_id, display_name, remote_address,
                android_certificate_fingerprint, desktop_certificate_fingerprint,
                pairing_nonce, sas, state, created_at, expires_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pair_request_id, device_id, display_name, remote_address,
             android_certificate_fingerprint, desktop_certificate_fingerprint,
             pairing_nonce, sas, DesktopPairingState.PAIRING_PENDING.value,
             created, expires, created),
        )
        self.connection.commit()
        return self.get(pair_request_id)  # type: ignore[return-value]

    def get(self, pair_request_id: str) -> PairingRequest | None:
        cursor = self.connection.execute(
            "SELECT * FROM android_pairing_requests_v2 WHERE pair_request_id = ?",
            (pair_request_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        values = dict(row) if hasattr(row, "keys") else dict(zip(
            (column[0] for column in cursor.description), row
        ))
        return PairingRequest(
            **{key: values[key] for key in (
                "pair_request_id", "device_id", "display_name", "remote_address",
                "android_certificate_fingerprint", "desktop_certificate_fingerprint",
                "pairing_nonce", "sas", "state", "created_at", "expires_at",
                "updated_at", "failure_reason",
            )},
            android_confirmed=bool(values["android_confirmed"]),
            desktop_confirmed=bool(values["desktop_confirmed"]),
        )

    def expire(self, pair_request_id: str, reason: str) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.connection.execute(
            """UPDATE android_pairing_requests_v2
               SET state = ?, failure_reason = ?, updated_at = ?
               WHERE pair_request_id = ? AND state NOT IN ('PAIRED', 'REJECTED')""",
            (DesktopPairingState.PAIRING_EXPIRED.value, reason, now, pair_request_id),
        )
        self.connection.commit()
