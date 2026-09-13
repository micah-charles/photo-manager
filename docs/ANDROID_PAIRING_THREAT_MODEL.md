# Android secure pairing threat model

## Scope

Photo Manager pairs a local desktop with a read-only PhotoVault Companion on
the same LAN. mDNS is discovery only; the pairing protocol authenticates the
peer and creates a trusted device record. Media transfer remains the existing
verified, resumable pipeline.

## Threats and controls

| Threat | Control |
|---|---|
| Malicious LAN device or MITM | Noise XX transcript + two-sided numeric comparison; mDNS is not trust |
| Replay or stale session | 120-second sessions, fresh ephemeral handshake, one-time state transitions |
| Pairing-code guessing/spam | explicit phone approval, bounded attempts and temporary rate limit |
| IP/port change | stable installation `device_id`; IP is only an address |
| Reinstall or changed key | pinned public-key fingerprint; identity change requires explicit re-pair |
| SQLite/browser secret leakage | SQLite stores only credential reference and public audit metadata; browser holds no private key |
| Logs leaking credentials | token/private-key/session fields are excluded from pairing audit events |
| Localhost browser-origin attack | desktop pairing/revoke endpoints require an allowed local UI Origin; browser never owns the key |

## Explicit limits

The checked-in Android APK uses Noise XX for pairing/reconnect and issues a
short-lived transfer session credential after identity verification. The
legacy token-authenticated HTTP path remains visibly labelled for older/manual
clients and is not silently upgraded to secure pairing.
