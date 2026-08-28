# Android integration final report

Status: in progress; real-device canonical CLI and packaged-app validation
remain open.

## Architecture

PySide6 UI and CLI call Python application services. A capability-based
PhotoSource boundary separates filesystem sources from AndroidMacMtpSource.
The Android source uses a macOS arm64 Objective-C IOUSBHost/MTP helper. JSON
lines carry normalized control metadata; object bytes use a separate bounded
binary stream. Python owns catalog, backup/import policy, SHA-256, history,
thumbnails, duplicate intelligence, and destinations.

## Migrated components

- IOUSBHost interface discovery and pipe setup from the proven POC.
- MTP session, device/storage metadata, object handles, ObjectInfo parsing.
- Pixel-specific root query behavior and association-folder handling.
- Bounded GetObject stream path.
- Native helper build script and optional PyInstaller inclusion.

## Implementation ladder

- Level 1 — PASS: Photo Manager audit.
- Level 2 — PASS: generic PhotoSource and normalized identity/item contracts.
- Level 3 — PASS: native macOS Android helper migrated and arm64 compiled.
- Level 4 — PENDING: Pixel detected through PhotoVault CLI from an unsandboxed Terminal.
- Level 5 — PENDING: DCIM/Camera listed through PhotoVault CLI.
- Level 6 — PENDING: one media object streamed and discarded on hardware.
- Level 7 — CODE READY, HARDWARE PENDING: one controlled media object copied.
- Level 8 — CODE READY, HARDWARE PENDING: SHA-256 verified copy.
- Level 9 — CODE READY, HARDWARE PENDING: source/catalog/history integration.
- Level 10 — PENDING: small multi-file import.
- Level 11 — PENDING: incremental already-imported detection.
- Level 12 — CODE READY, UI HARDWARE PENDING: basic PySide6 Android source page with background discovery worker.
- Level 13 — PENDING: packaged application validation.

## Tests

The baseline suite passed 47 tests before Android changes. The current suite
passes 52 tests; four optional PySide6 tests are skipped because PySide6 is
not installed. The native helper compiles as arm64. Hardware tests must run
from the user's Terminal rather than the Codex sandbox.

## Safety

No phone deletes, source writes, root, sudo, DeviceCapture, SIP change,
Gatekeeper bypass, kext, or privileged daemon was introduced. No real serial,
private filenames, EXIF, location metadata, or photo content is committed.

## Remaining blockers

The canonical helper and stream still require real Pixel Terminal validation.
The packaged app requires clean-machine signing/notarization/App Sandbox
validation. UI integration and production import/history wiring should wait
until the one-object hardware stream is proven.
