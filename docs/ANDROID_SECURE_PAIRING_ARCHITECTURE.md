# Android secure pairing architecture

The pairing boundary is deliberately separate from the verified media
transfer engine.

```text
Android NSD advertisement (public metadata)
        |
Python zeroconf discovery
        |
Noise XX handshake (protocol v1)
        |
same six-digit SAS on both peers
        |
explicit confirmation on Android + desktop
        |
pinned public identity + OS credential reference
        |
short-lived authenticated session
        |
existing read-only HTTP media transfer
```

The current sprint implements the Python protocol/session foundation, a real
Python ↔ Java Noise XX interoperability test, mDNS discovery listener,
pairing audit schema, Android NSD advertisement, and a short-lived transfer
session credential derived locally after authenticated pairing/reconnect. The checked-
in Android APK advertises `pairing=yes` only while the user explicitly enables
pairing mode. The legacy bearer-token path remains available for older/manual
clients as an explicit compatibility path.

SQLite stores device ID, public-key fingerprint, protocol version, timestamps,
and a credential reference only. Private material belongs in macOS Keychain or
Windows Credential Manager through `KeyringCredentialStore`; browser
localStorage is not used for it.

IP addresses are resolved endpoints, never identities. A reinstall creates a
new installation ID and must be explicitly paired again. Discovery failure can
fall back to the existing manual URL/token path under Advanced settings.
