"""Persistence for non-secret trusted Android pairing metadata."""
from __future__ import annotations

from sqlite3 import Connection
from datetime import datetime, timedelta, timezone

from photovault.catalog.scanner import utc_now
from photovault.sources.base import SourceIdentity
from photovault.catalog.sources import register_source


def source_id_for_device(device_id: str) -> str:
    """Use the installation identity, never the current IP address."""
    import hashlib
    return "android_wifi_" + hashlib.sha256(device_id.encode()).hexdigest()[:24]


def trust_android_device(connection: Connection, *, device_id: str, display_name: str,
                         public_key_fingerprint: str, credential_reference_id: str,
                         protocol_version: str = "photovault-pairing-v1") -> str:
    source_id = source_id_for_device(device_id)
    existing = connection.execute(
        "SELECT public_key_fingerprint FROM trusted_android_devices WHERE device_id=? AND revoked_at IS NULL",
        (device_id,),
    ).fetchone()
    if existing is not None and str(existing[0]) != public_key_fingerprint:
        raise ValueError("security identity changed; explicit forget and re-pair is required")
    register_source(connection, SourceIdentity(source_id, "Google", "Android", display_name, "android_companion_wifi"))
    now = utc_now()
    connection.execute(
        """INSERT INTO trusted_android_devices(
            device_id, source_id, display_name, public_key_fingerprint,
            credential_reference_id, protocol_version, paired_at,
            last_authenticated_at, revoked_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, '{}')
        ON CONFLICT(device_id) DO UPDATE SET
            source_id=excluded.source_id, display_name=excluded.display_name,
            public_key_fingerprint=excluded.public_key_fingerprint,
            credential_reference_id=excluded.credential_reference_id,
            protocol_version=excluded.protocol_version,
            last_authenticated_at=excluded.last_authenticated_at,
            revoked_at=NULL""",
        (device_id, source_id, display_name, public_key_fingerprint,
         credential_reference_id, protocol_version, now, now),
    )
    connection.commit()
    return source_id


def list_trusted_android_devices(connection: Connection) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(
        """SELECT device_id, source_id, display_name, public_key_fingerprint,
                  credential_reference_id, protocol_version, paired_at,
                  last_authenticated_at, revoked_at
           FROM trusted_android_devices ORDER BY display_name, device_id"""
    )]


def revoke_android_device(connection: Connection, device_id: str) -> None:
    connection.execute("UPDATE trusted_android_devices SET revoked_at=? WHERE device_id=?", (utc_now(), device_id))
    connection.commit()


def touch_android_device(connection: Connection, device_id: str) -> None:
    connection.execute("UPDATE trusted_android_devices SET last_authenticated_at=? WHERE device_id=? AND revoked_at IS NULL", (utc_now(), device_id))
    connection.commit()


def record_pairing_session(connection: Connection, *, session_id: str, device_id: str,
                           display_name: str, state: str, sas: str | None = None,
                           public_key_fingerprint: str | None = None,
                           error_code: str | None = None) -> None:
    now = utc_now()
    connection.execute(
        """INSERT INTO android_pairing_sessions(
            id, device_id, display_name, state, sas, public_key_fingerprint,
            protocol_version, created_at, expires_at, updated_at, error_code
        ) VALUES (?, ?, ?, ?, ?, ?, 'photovault-pairing-v1', ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET state=excluded.state, sas=excluded.sas,
            public_key_fingerprint=excluded.public_key_fingerprint,
            updated_at=excluded.updated_at, error_code=excluded.error_code""",
        (session_id, device_id, display_name, state, sas, public_key_fingerprint,
         now, (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(timespec="seconds"), now, error_code),
    )
    connection.commit()
