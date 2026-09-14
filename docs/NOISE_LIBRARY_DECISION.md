# Noise library decision

The Python side uses `noiseprotocol` 0.3.1, which supports Noise XX with
X25519, ChaChaPoly and SHA-256, and uses `cryptography` for primitives. LAN
discovery uses `zeroconf` 0.151.3. Desktop secrets are delegated to
`keyring`, which maps to macOS Keychain or Windows Credential Manager.

The Android project uses a dependency-free `javac`/`d8` build, so the reviewed
MIT source from `rweather/noise-java` is vendored under
`android-companion/third_party/noise-java`. A test-only Java responder and the
Python initiator now complete a real Noise XX handshake with matching
transcript hashes. No custom ECDH, AEAD, HKDF, certificate, or token-to-SAS
substitute is used.

Reference research: [Noise Protocol Framework](https://noiseprotocol.org/),
[noiseprotocol Python](https://github.com/plizonczyk/noiseprotocol), and
[Noise-Java](https://github.com/rweather/noise-java).
