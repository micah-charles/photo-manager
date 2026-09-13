# Secure Android pairing sprint report

## Completed in this sprint

1. Added pairing protocol constants and typed lifecycle states.
2. Added a real Python Noise XX handshake interoperability test with X25519,
   ChaChaPoly and SHA-256.
3. Derived the six-digit comparison value from the handshake transcript;
   neither peer sends a pre-generated code.
4. Added two-sided confirmation, 120-second expiry, cancellation and bounded
   rate limiting.
5. Added mDNS/DNS-SD discovery using `zeroconf`; TXT records contain no token,
   private key or session secret.
6. Added SQLite audit tables for trusted devices and pairing sessions.
7. Added OS credential-store abstraction and test store; no private key is
   stored in SQLite or browser state.
8. Added Android NSD advertisement while sharing is active and unregisters it
   when sharing stops.
9. Added a web discovery panel to Android Backup.
10. Added trusted-device persistence after both confirmations, stable source
    mapping, identity-change rejection, and a local-only revoke endpoint.
11. Added automatic reconnect on trusted mDNS device appearance using pinned
    identity; IP changes do not create another source.
12. Kept the existing range, resume, SHA-256, atomic copy, incremental skip,
    worker and batch-fsync transfer pipeline unchanged.

## Verification

- `PYTHONPATH=src .venv/bin/python -m unittest tests.test_pairing tests.test_android_wifi tests.test_web tests.test_android_backup_profiles -q`
  passed: 19 tests.
- `zsh scripts/build_android_companion.sh` passed and produced
  `android-companion/build/photovault-companion-debug.apk`.

## Current acceptance gates

- Complete the full live flow on a real Pixel and verify the Android UI
  confirmation/reconnect experience.
- The Android APK now has a live pairing-mode button, transcript SAS display,
  single-session phone confirmation, and Keystore-backed static identity.
  Media transfer accepts the short-lived session credential derived by both
  peers after pairing/reconnect; it is not sent in the handshake response.
  The legacy bearer-token HTTP API remains only for older manual clients.
- Add Keychain/Windows Credential Manager device tests on real hosts.
- Perform real Pixel discovery, pairing, restart/reconnect, Wi-Fi change,
  revocation and transfer regression QA. No real hardware pass is claimed in
  this report.
