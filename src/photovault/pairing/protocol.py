"""Pairing state and Noise XX helpers.

This module deliberately keeps long-term private keys out of SQLite.  The
actual key is supplied by a CredentialStore implementation (OS keychain on a
real desktop, TestCredentialStore in tests).  HTTP bearer tokens remain a
legacy compatibility path and are never upgraded implicitly.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum

PAIRING_PROTOCOL = "photovault-pairing-v1"
PAIRING_TTL_SECONDS = 120
TRANSFER_SESSION_CONTEXT = b"PhotoVault transfer session v1"


class PairingError(ValueError):
    pass


class PairingState(StrEnum):
    DISCOVERED = "DISCOVERED"
    CONNECTING = "CONNECTING"
    HANDSHAKING = "HANDSHAKING"
    AWAITING_NUMERIC_CONFIRMATION = "AWAITING_NUMERIC_CONFIRMATION"
    LOCAL_CONFIRMED = "LOCAL_CONFIRMED"
    REMOTE_CONFIRMED = "REMOTE_CONFIRMED"
    PAIRED = "PAIRED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


def sas_for_handshake(handshake_hash: bytes) -> str:
    """Render the six-digit comparison value from the Noise transcript hash."""
    if len(handshake_hash) < 8:
        raise PairingError("handshake hash is too short")
    value = int.from_bytes(hashlib.sha256(handshake_hash).digest()[:8], "big") % 1_000_000
    return f"{value:06d}"[:3] + " " + f"{value:06d}"[3:]


def transfer_session_token(handshake_hash: bytes) -> str:
    """Derive an opaque transfer credential without sending it over the LAN."""
    if len(handshake_hash) < 32:
        raise PairingError("handshake hash is too short")
    digest = hmac.new(handshake_hash, TRANSFER_SESSION_CONTEXT, hashlib.sha256).digest()
    import base64
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def run_noise_xx_in_memory(prologue: bytes = PAIRING_PROTOCOL.encode()) -> tuple[str, str, bytes]:
    """Run a real Noise XX handshake for interoperability tests.

    The Android side still needs the reviewed Java Noise implementation before
    this helper is connected to the live Companion protocol.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from noise.connection import Keypair, NoiseConnection
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise PairingError("install the pairing optional dependencies") from exc

    private_i = X25519PrivateKey.generate().private_bytes_raw()
    private_r = X25519PrivateKey.generate().private_bytes_raw()
    initiator = NoiseConnection.from_name(b"Noise_XX_25519_ChaChaPoly_SHA256")
    responder = NoiseConnection.from_name(b"Noise_XX_25519_ChaChaPoly_SHA256")
    initiator.set_as_initiator(); responder.set_as_responder()
    initiator.set_prologue(prologue); responder.set_prologue(prologue)
    initiator.set_keypair_from_private_bytes(Keypair.STATIC, private_i)
    responder.set_keypair_from_private_bytes(Keypair.STATIC, private_r)
    initiator.start_handshake(); responder.start_handshake()
    responder.read_message(initiator.write_message())
    initiator.read_message(responder.write_message())
    responder.read_message(initiator.write_message())
    if initiator.get_handshake_hash() != responder.get_handshake_hash():
        raise PairingError("Noise peers produced different handshake transcripts")
    sas = sas_for_handshake(initiator.get_handshake_hash())
    return sas, sas_for_handshake(responder.get_handshake_hash()), initiator.get_handshake_hash()


@dataclass
class PairingSession:
    id: str
    device_id: str
    display_name: str
    state: PairingState = PairingState.DISCOVERED
    sas: str | None = None
    handshake_hash: str | None = None
    public_key_fingerprint: str | None = None
    local_confirmed: bool = False
    remote_confirmed: bool = False
    created_at: float = 0.0
    expires_at: float = 0.0
    error_code: str | None = None

    def __post_init__(self) -> None:
        now = time.time()
        if not self.created_at: self.created_at = now
        if not self.expires_at: self.expires_at = self.created_at + PAIRING_TTL_SECONDS

    def ensure_live(self) -> None:
        if time.time() >= self.expires_at:
            self.state = PairingState.EXPIRED
            raise PairingError("pairing session expired")

    def set_handshake(self, handshake_hash: bytes, public_key_fingerprint: str) -> None:
        self.ensure_live()
        self.handshake_hash = handshake_hash.hex()
        self.public_key_fingerprint = public_key_fingerprint
        self.sas = sas_for_handshake(handshake_hash)
        self.state = PairingState.AWAITING_NUMERIC_CONFIRMATION

    def confirm(self, side: str) -> None:
        self.ensure_live()
        if self.state != PairingState.AWAITING_NUMERIC_CONFIRMATION and self.state not in {PairingState.LOCAL_CONFIRMED, PairingState.REMOTE_CONFIRMED}:
            raise PairingError(f"cannot confirm from {self.state}")
        if side == "local": self.local_confirmed = True
        elif side == "remote": self.remote_confirmed = True
        else: raise PairingError("confirmation side must be local or remote")
        if self.local_confirmed and self.remote_confirmed: self.state = PairingState.PAIRED
        elif self.local_confirmed: self.state = PairingState.LOCAL_CONFIRMED
        else: self.state = PairingState.REMOTE_CONFIRMED

    def cancel(self) -> None:
        if self.state != PairingState.PAIRED: self.state = PairingState.CANCELLED


class PairingSessionStore:
    """Bounded in-process session registry; SQLite persists only audit state."""

    def __init__(self) -> None:
        self._sessions: dict[str, PairingSession] = {}
        self._failures: dict[str, list[float]] = {}

    def start(self, device_id: str, display_name: str) -> PairingSession:
        now = time.time()
        recent = [x for x in self._failures.get(device_id, []) if now - x < 60]
        if len(recent) >= 5: raise PairingError("pairing temporarily rate limited")
        session = PairingSession("pair_" + uuid.uuid4().hex, device_id, display_name, state=PairingState.CONNECTING)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> PairingSession:
        try: session = self._sessions[session_id]
        except KeyError as exc: raise PairingError("unknown pairing session") from exc
        if time.time() >= session.expires_at and session.state not in {PairingState.PAIRED, PairingState.CANCELLED, PairingState.EXPIRED}:
            session.state = PairingState.EXPIRED
        return session

    def fail(self, session_id: str, code: str) -> PairingSession:
        session = self.get(session_id); session.state = PairingState.FAILED; session.error_code = code
        self._failures.setdefault(session.device_id, []).append(time.time())
        return session

    def cancel(self, session_id: str) -> PairingSession:
        session = self.get(session_id); session.cancel(); return session
