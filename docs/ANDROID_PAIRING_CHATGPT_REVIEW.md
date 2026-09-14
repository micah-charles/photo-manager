# Photo Manager Android Pairing Review Package

## Review question

Please review the secure Android Wi-Fi pairing implementation and explain why the
Photo Manager Android Backup screen can appear to do nothing after the Android
user confirms the pairing number.

## Intended protocol

1. Android Companion advertises public mDNS metadata only.
2. The user opens `Pair new computer` on Android for a two-minute window.
3. Photo Manager discovers the device and calls `POST /api/android/pair`.
4. The Python client runs a Noise XX handshake over three messages:
   - desktop initiator message 1
   - Android responder message 2
   - desktop initiator message 3
5. Both sides derive the same six-digit SAS from the completed transcript.
6. Android confirms locally, then Photo Manager confirms through
   `POST /api/android/pair/{session_id}/confirm`.
7. Both sides derive an HMAC-based short-lived transfer session token from the
   Noise handshake hash. The legacy URL token is not used for secure transfers.
8. The Android media server remains read-only. It only exposes manifests,
   metadata, and range reads.

## Current architecture

```text
Android Companion
  ├─ MediaStore read-only HTTP server :8765
  ├─ mDNS _photovault._tcp advertisement
  ├─ Noise XX responder
  └─ Android Keystore encrypted static identity
          │ LAN / HTTP handshake messages
          ▼
Photo Manager local server :8767
  ├─ mDNS discovery cache
  ├─ GET /api/android/devices
  ├─ POST /api/android/pair
  ├─ POST /api/android/pair/{id}/confirm
  ├─ SQLite trusted identity and pairing audit records
  └─ Python Noise XX initiator + keyring desktop identity
          │
          ▼
Browser Android Backup UI
  ├─ discovered device card
  ├─ Pair button
  ├─ SAS toast / confirmation state
  └─ secure session token passed to verified backup jobs
```

## Root-cause history found during live testing

1. **Empty browser response:** `server.py` caught `AndroidCompanionUnavailable`
   without importing the class. A downstream phone failure therefore caused a
   `NameError` inside the exception handler and closed the browser socket.
2. **Phone unavailable:** the mDNS record could remain visible while
   `192.168.1.159:8765` was not listening. The browser saw a stale device.
3. **Keystore failure:** Android encryption supplied a caller IV. Android
   Keystore rejected it with `Caller-provided IV not permitted`. Encryption now
   lets the cipher create the IV and stores that IV with the ciphertext.
4. **Handshake failure:** Android called `session.sas()` after message 1, before
   the Noise handshake was complete. This raised `Handshake has not completed`.
5. **Invalid SAS:** SAS used a signed Java `long`, producing values such as
   `-98 189`. It now uses a positive `BigInteger` calculation.
6. **Lost confirmation state:** pairing sessions are currently held in the Mac
   server process. Restarting the server invalidates the Android-side waiting
   session from the UI's point of view.
7. **Stale discovery UI:** mDNS TXT data can lag behind the phone's live pairing
   state. The server now probes the public Android pairing-status endpoint with
   GET and the UI polls device state every three seconds.

## What was last proven

The latest installed-compatible Android build successfully returned:

```text
POST /api/pair/start -> 201
Noise handshake -> completed
SAS -> valid six-digit value (example: 485 058)
fingerprint -> 5a470a7681389d7d
```

The remaining UX concern is confirmation-state visibility. The browser only
changes the device button to `Confirm number` after the `/api/android/pair`
request completes. If the session expires, the server restarts, the browser
has stale JavaScript, or the phone stops listening, the UI can remain at
`Pair`/`Advanced` and show only a transient toast. This is the main area for
an independent review.

## Files included in this review package

- `src/photovault/pairing/`
- `src/photovault/sources/android_wifi.py`
- `src/photovault/web/server.py`
- `src/photovault/web/static/app.js`
- `src/photovault/web/static/index.html`
- `src/photovault/web/static/style.css`
- `android-companion/src/com/photovault/companion/MainActivity.java`
- `android-companion/src/com/photovault/companion/NoisePairingResponder.java`
- `android-companion/third_party/noise-java/`
- `tests/test_pairing.py`
- `tests/test_android_wifi.py`
- `tests/java/NoiseHandshakeResponder.java`
- `scripts/build_android_companion.sh`
- `pyproject.toml`
- `docs/ANDROID_PAIRING_THREAT_MODEL.md`
- `docs/ANDROID_SECURE_PAIRING_ARCHITECTURE.md`
- `docs/NOISE_LIBRARY_DECISION.md`

## Reproduction commands

Check phone state:

```bash
curl -sS http://PHONE_IP:8765/api/pair/status
```

Expected before pairing:

```json
{"ok":true,"pairing":true,"protocol":"photovault-pairing-v1"}
```

Run the same Python client used by the UI:

```bash
PYTHONPATH=src .venv/bin/python -c \
'from photovault.sources.android_wifi import AndroidCompanionWifiSource; \
s=AndroidCompanionWifiSource("http://PHONE_IP:8765", "", timeout=10); \
print(s.pair(desktop_name="Photo Manager"))'
```

## Review focus

- Is the three-message Noise XX state machine mapped correctly on both sides?
- Should pairing sessions survive a Mac server restart?
- Should the UI show a durable pairing state instead of a toast?
- Should Android confirmation be correlated to a displayed SAS/session ID?
- Should the server use a persistent pairing-session store rather than process
  memory?
- Are the mDNS status probe and fallback rules correct?
- Are error messages and retry behavior clear enough for a user?
