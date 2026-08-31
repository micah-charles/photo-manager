# Android transfer architecture sprint

## Executive summary

Track A — USB/libusb: **NOT VIABLE AS CURRENTLY IMPLEMENTED**. A disposable
arm64 libusb MTP helper successfully probes the Pixel and opens a session, but
its real-device JPEG stream read exactly one 64 KiB receive buffer before the
next bulk-IN returned `LIBUSB_ERROR_IO`. The subsequent CloseSession timed out.
Changing only from raw `IOUSBHost` to a basic synchronous libusb loop therefore
does not solve the sustained-read failure on this Pixel/macOS combination.

Track B — Android Companion Wi-Fi: **SINGLE-IMAGE PIXEL/LAN PASS; MORE
EVIDENCE NEEDED**. A minimal Android MediaStore companion builds to a signed
debug APK. Its fixed MediaStore manifest path, complete stream, and Range
behavior passed in an Android 35 arm64 emulator. The updated app then passed a
real Pixel device/manifest check and one complete image stream over LAN. Large
transfer, sequential, and recovery behavior remain unmeasured.

Recommended next step: run the short manual checklist below before selecting a
primary transport. Neither prototype has a measured complete JPEG, large-file,
or recovery result yet.

## Track A — USB/libusb

### Implementation

`native/macos/android_mtp_libusb/main.c` is a standalone arm64 command-line
helper linked to Homebrew libusb 1.0.30. It deliberately does not alter the
existing `IOUSBHost` helper or Python MTP source.

The helper implements only the narrow POC needed to isolate transport:

- Pixel VID/PID open and interface 0 claim;
- OpenSession, GetStorageIDs, GetObjectHandles, GetObjectInfo;
- lazy root -> DCIM -> Camera resolution;
- fresh JPEG selection and exact framed GetObject stream to stdout;
- explicit lifecycle states: opened, claimed, MTP session;
- CloseSession/release only when that state was successfully reached.

This differs from the frozen reference backend by using libusb bulk transfers
and its macOS IOUSBLib user-client path, not `IOUSBHost` bulk streaming.

### Dependency and licence boundary

The POC has a runtime/build dependency on libusb only; it does not embed or
link OpenMTP, Kalam, go-mtpx, go-mtpfs, libmtp, or Whoozle code. libusb is
LGPL-2.1-or-later; production packaging needs a separate licence/distribution
review before adoption. No third-party source was copied.

### Build and test

```zsh
cd /Volumes/ExtremePro/project/codex/photo-manager-github
zsh scripts/build_android_libusb_mtp_helper.sh
./native/macos/android_mtp_libusb/photovault-android-libusb-mtp --probe
./native/macos/android_mtp_libusb/photovault-android-libusb-mtp --stream-test DCIM/Camera > /tmp/photovault-libusb-test.jpg
shasum -a 256 /tmp/photovault-libusb-test.jpg
```

Build result: PASS, Mach-O 64-bit arm64.

| Test | Result |
| --- | --- |
| Pixel enumeration / OpenSession / storage | PASS (real Pixel) |
| Complete JPEG | FAIL: 65,536 bytes written; next bulk-IN `LIBUSB_ERROR_IO` |
| Sequential files | NOT TESTED |
| 100 MB+ object | NOT TESTED |
| Throughput | NOT MEASURED |
| Cancellation/recovery without reconnect | NOT TESTED |

Real-device result (2026-08-31): `--stream-test DCIM/Camera` wrote 65,536 bytes
of a JPEG before the next 64 KiB receive returned `LIBUSB_ERROR_IO`; total wall
time was 22.30 seconds. The helper then reported a CloseSession timeout. This
is a failed full-object transfer, not a partial success. It is also evidence
against treating a simple libusb transport swap as equivalent to OpenMTP's
complete transport and lifecycle stack.

Known issue: libusb lifecycle needs further investigation only if the USB path
is resumed. OpenMTP showed an independent `libusb_release_interface()`
assertion on macOS 26, hence this POC never releases an interface it did not
successfully claim.

## Track B — Android Companion Wi-Fi

### Architecture and security

`android-companion/` is a Java Android 29+ proof of concept. The app requests
only `READ_MEDIA_IMAGES` and `READ_MEDIA_VIDEO`, queries MediaStore, and never
uses a write/delete API. A small local HTTP server exposes:

- `GET /api/device?token=...`
- `GET /api/media?token=...`
- `GET /api/media/{id}?token=...` with HTTP `Range` support.

At every launch the app creates a new 144-bit random token and displays the
LAN URL/token. This avoids an unauthenticated permanent server but is not
production security: traffic is unencrypted, the token appears in URLs, and
the server binds to available interfaces. Production needs authenticated
pairing, TLS or an equivalent protected local channel, token storage/rotation,
and Bonjour or another constrained discovery mechanism.

The desktop implementation is `AndroidCompanionWifiSource` behind the same
existing `PhotoSource` contract. It adds `identity`, a flat MediaStore
manifest, complete stream, and range-read capabilities without changing the
catalog, backup, import, or external-drive safety rules.

### Build and test

The global Gradle installation cannot load its arm64 native platform library
on this Mac. The reproducible build script therefore uses only installed
Android SDK build-tools (`aapt2`, `d8`, `zipalign`, `apksigner`) and `javac`:

```zsh
cd /Volumes/ExtremePro/project/codex/photo-manager-github
zsh scripts/build_android_companion.sh
```

Build result: PASS. Output:
`android-companion/build/photovault-companion-debug.apk` (signed debug APK).

Android 35 arm64 runtime regression result (2026-08-31): PASS. The first real
Pixel request exposed a server-side manifest failure: the app built an SQL
`LIMIT` suffix into its sort-order string, which recent MediaProvider rejects;
the request handler swallowed that exception and closed the connection. Commit
`0b673a2` replaces that construction with Android's public query-arguments API
and logs any unexpected handler exception. In a disposable emulator, the
desktop client then passed device discovery and manifest retrieval, streamed a
40,139-byte JPEG completely, and range-streamed from offset 1,024. The
39,115-byte range result had the exact SHA-256 of the fixture tail. No
unhandled Companion exception appeared in the emulator log.

Physical Pixel/LAN result (2026-08-31): PASS for one complete image. After
confirming the Pixel's local `/api/device` endpoint and restored LAN
reachability, the desktop client received exactly the manifest-declared
162,584 bytes in 0.196 seconds (about 0.83 MB/s) and discarded those bytes
after measurement. No Pixel file was changed or retained on the Mac.

Background-sharing regression result (2026-08-31): PASS in the Android 35
emulator. Build `0.3-background-sharing` runs the local server in a visible
`dataSync` foreground service, with a persistent notification and an explicit
Stop action. It holds only the CPU and Wi-Fi locks required for an active
sharing session; it does not keep the display on. The service responded to
`/api/device` both before and after the emulator screen was turned off, and
Android reported it as an active foreground service with the `dataSync` type.
The UI offers 10 minutes, 1 hour, and “until stopped”; the last option is
labelled as a maximum of about six hours because Android 15 limits `dataSync`
foreground-service time in a 24-hour period. A physical Pixel screen-off test
is still pending.

After installation, use the URL/token shown by the app:

```zsh
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault-wifi.db \
  android-wifi --url http://PHONE_IP:8765 --token TOKEN devices
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault-wifi.db \
  android-wifi --url http://PHONE_IP:8765 --token TOKEN list --limit 20
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault-wifi.db \
  android-wifi --url http://PHONE_IP:8765 --token TOKEN stream OBJECT_ID

# Read-only folder inventory: path, item count, total bytes, images, videos.
PYTHONPATH=src python3 -m photovault.cli \
  android-wifi --url http://PHONE_IP:8765 --token TOKEN folders
PYTHONPATH=src python3 -m photovault.cli \
  android-wifi --url http://PHONE_IP:8765 --token TOKEN folder DCIM/Camera

# Transfer benchmark: every byte is discarded on the Mac after timing.
PYTHONPATH=src python3 -m photovault.cli \
  android-wifi --url http://PHONE_IP:8765 --token TOKEN \
  benchmark-folder DCIM/Camera

# This is a plan only: it neither reads photo bytes nor writes the destination.
PYTHONPATH=src python3 -m photovault.cli \
  --catalog /Volumes/EXTERNAL_DRIVE/photovault-benchmark.db \
  android-wifi --url http://PHONE_IP:8765 --token TOKEN \
  copy-folder DCIM/Camera /Volumes/EXTERNAL_DRIVE/PhotoVault-Camera-Test
# Add --confirm-copy only after checking the plan. Copies are atomically
# written, SHA-256 verified, and never overwrite a conflicting destination.
```

| Test | Result |
| --- | --- |
| Device information | PASS: automated client, Android 35 emulator, updated Pixel/LAN |
| Media manifest | PASS: Android 35 emulator + updated Pixel/LAN |
| Complete image | PASS: emulator fixture + Pixel 162,584-byte stream |
| Sequential files | NOT TESTED |
| 100 MB+ object | NOT TESTED |
| Throughput | NOT MEASURED |
| Range/resume | PASS: emulator offset stream hash match; Pixel/LAN recovery NOT TESTED |

No LocalSend code or protocol was incorporated. Its discovery/pairing approach
remains reference material only.

## A/B comparison

| Criterion | USB MTP/libusb | Android Companion Wi-Fi |
| --- | --- | --- |
| Complete image | FAIL: 64 KiB then bulk-IN I/O error | PASS: emulator + one Pixel image |
| 100 MB+ file | NOT TESTED | NOT TESTED |
| Average MB/s | NOT MEASURED | NOT MEASURED |
| Resume | NOT TESTED | Protocol/client Range support implemented; NOT TESTED |
| Error recovery | State-gated helper design; NOT TESTED | Fresh token/server restart design; NOT TESTED |
| Requires Android app | No | Yes |
| Requires cable | Yes | No |
| macOS complexity | High: libusb/lifecycle/package review | Low: standard HTTP client |
| Windows portability | Plausible with libusb validation | High: standard HTTP client |
| Implementation complexity | Medium/high | Medium |
| Long-term maintainability | Needs USB device matrix | Promising if pairing/security is completed |

## Recommendation

The current basic libusb POC is **not** a viable fallback or primary transport:
it has reproduced the same class of sustained-read failure after beginning the
payload. A substantially different USB implementation/lifecycle model would
need separate evidence before further USB work. Wi-Fi is the remaining primary
candidate direction for portability and recoverable Range semantics. Its app
and protocol path now has Android runtime evidence plus one real Pixel image;
it must still earn primary status with sequential, large-file, and interruption
tests.

The raw IOUSBHost backend remains frozen as a reference backend, not removed.

## Tomorrow's manual test checklist

1. Reconnect/unlock Pixel and select **File Transfer / Android Auto**.
2. Treat the current basic libusb experiment as a recorded failure; do not use
   its partial output as a photo or continue tuning buffer sizes.
3. Install the APK: `adb install -r android-companion/build/photovault-companion-debug.apk`.
4. Open **PhotoVault Companion**, grant Photos, Videos, and Notifications
   permission, then choose **Share for 10 minutes**, **Share for 1 hour**, or
   **Share until stopped (up to 6 hours)**. The screen may be turned off; use
   the app or the persistent notification’s **Stop** action to end sharing.
5. Copy the displayed URL and token into the three Track B commands above.
6. Run `list`; choose one JPEG `OBJECT_ID`; run `stream` and record bytes/time.
7. Repeat `stream` for two more photos without restarting the app.
8. If there is a safe 100 MB+ video, stream it and record elapsed time.
9. Send the exact outputs back; do not use external backup disks or delete
    phone media.

## Git and validation summary

Branch: `feature/android-source-macos`.

New source: libusb helper/build script, Android companion/build script,
desktop Wi-Fi source, CLI commands, and one automated Wi-Fi protocol test.

Validation: `PYTHONPATH=src python3 -m unittest discover -s tests -v` passed
61 tests with 4 optional PySide6 tests skipped. Both native libusb helper and
Android debug APK builds passed. Real-device tests are intentionally marked
NOT TESTED rather than inferred from build success.
