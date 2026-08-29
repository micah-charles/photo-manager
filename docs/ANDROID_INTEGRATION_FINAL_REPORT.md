# Android integration final report

Status: real-device discovery, storage enumeration, and lazy DCIM/Camera
listing pass from the canonical repository. Level 6 is blocked by a
reproducible raw-IOUSBHost sustained-payload failure. Real-device import and
packaged-app validation remain pending.

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
- Level 4 — PASS: Pixel 8 Pro detected through PhotoVault CLI from the user's unsandboxed Terminal.
- Level 5 — PASS: canonical CLI resolved root -> DCIM -> Camera and returned
  the first 50 of 6,674 Camera objects from the Pixel 8 Pro.
- Level 6 — BLOCKED: same-session media streaming reaches valid payload bytes,
  then the raw IOUSBHost bulk-IN path stops responding after cumulative
  transfer. Full, partial, synchronous, asynchronous, 16 KiB, max-packet, and
  kernel-backed-buffer controls have isolated the boundary.
- Level 7 — CODE READY, HARDWARE PENDING: one controlled media object copied.
- Level 8 — CODE READY, HARDWARE PENDING: SHA-256 verified copy.
- Level 9 — CODE READY, HARDWARE PENDING: source/catalog/history integration.
- Level 10 — CODE READY, HARDWARE PENDING: reviewed folder import command and batch service.
- Level 11 — CODE READY, MOCK VERIFIED, HARDWARE PENDING: source-relative import records classify already-imported items without filename-only matching.
- Level 12 — CODE READY, UI HARDWARE PENDING: basic PySide6 Android source page with background discovery worker.
- Level 13 — PENDING: packaged application validation.

## Tests

The baseline suite passed 47 tests before Android changes. The current suite
passes 60 tests; four optional PySide6 tests are skipped because PySide6 is
not installed. The native helper compiles as arm64. Hardware tests run from
the user's normal Terminal because the Codex process sandbox does not have a
reliable claim on the Pixel MTP interface.

Real-device Level 5 evidence: the canonical CLI returned `PAGE 0 50 6674 50`.
The first three objects matched the proven POC handles and metadata samples.
No private photo content or complete device serial was captured.

## Safety

No phone deletes, source writes, root, sudo, DeviceCapture, SIP change,
Gatekeeper bypass, kext, or privileged daemon was introduced. No real serial,
private filenames, EXIF, location metadata, or photo content is committed.

## Resolved integration failure

The first canonical implementation repeated storage queries before every
folder listing and eagerly requested ObjectInfo for every child. This changed
the known-good POC transaction sequence: the Camera GetObjectHandles request
was delayed to transaction 40 and failed with `Unable to send IO`. The source
now caches storage metadata, resolves each path component lazily, and pages
Camera metadata in batches of 50. This restores the proven POC traversal
shape and prevents an eager 6,674-object metadata crawl.

The helper cleanup path also previously dereferenced a null optional payload
while closing an MTP session. That crash could leave the device session in a
state requiring a physical reconnect. Cleanup now accepts a null payload,
destroys the IOUSBHost interface on every exit, and has native and Python
regression coverage.

## Remaining blockers

Level 6 requires a bounded mature-client control test and an explicit
transport decision; see `ANDROID_MTP_TRANSPORT_REGRESSION_REPORT.md`. Levels
7–11 remain gated by Level 6. Level 12 needs UI hardware validation. The
packaged app requires PyInstaller installation plus clean-machine
signing/notarization/App Sandbox validation. The current UI exposes read-only
discovery/storage information; folder browsing/import controls can follow
successful hardware stream validation.
