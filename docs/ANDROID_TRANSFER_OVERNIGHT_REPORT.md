# Android transfer architecture sprint

## Executive summary

Track A — USB/libusb: **NEEDS MORE EVIDENCE**. A disposable arm64 libusb MTP
helper now builds and implements a state-gated session lifecycle plus a
same-session `DCIM/Camera` JPEG stream experiment. It has not been run against
the Pixel because this Codex process does not have a reliable USB claim.

Track B — Android Companion Wi-Fi: **NEEDS MORE EVIDENCE**. A minimal Android
MediaStore companion builds to a signed debug APK, and the desktop read-only
client has an automated manifest/Range-stream test. It has not yet been
installed or tested on the Pixel/LAN.

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
| Pixel enumeration | NOT TESTED (hardware sandbox boundary) |
| Complete JPEG | NOT TESTED |
| Sequential files | NOT TESTED |
| 100 MB+ object | NOT TESTED |
| Throughput | NOT MEASURED |
| Cancellation/recovery without reconnect | NOT TESTED |

Known issue: libusb lifecycle needs real-device validation. OpenMTP showed an
independent `libusb_release_interface()` assertion on macOS 26, hence this POC
never releases an interface it did not successfully claim.

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

After installation, use the URL/token shown by the app:

```zsh
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault-wifi.db \
  android-wifi --url http://PHONE_IP:8765 --token TOKEN devices
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault-wifi.db \
  android-wifi --url http://PHONE_IP:8765 --token TOKEN list --limit 20
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault-wifi.db \
  android-wifi --url http://PHONE_IP:8765 --token TOKEN stream OBJECT_ID
```

| Test | Result |
| --- | --- |
| Device information | AUTOMATED client test PASS; Pixel/LAN NOT TESTED |
| Media manifest | AUTOMATED client test PASS; Pixel/LAN NOT TESTED |
| Complete JPEG | NOT TESTED |
| Sequential files | NOT TESTED |
| 100 MB+ object | NOT TESTED |
| Throughput | NOT MEASURED |
| Range/resume | HTTP Range + client offset implemented; real recovery NOT TESTED |

No LocalSend code or protocol was incorporated. Its discovery/pairing approach
remains reference material only.

## A/B comparison

| Criterion | USB MTP/libusb | Android Companion Wi-Fi |
| --- | --- | --- |
| Complete JPEG | NOT TESTED | NOT TESTED |
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

Both paths are **NEEDS MORE EVIDENCE**. USB is still a viable fallback or
primary candidate if the libusb helper completes several JPEGs and a large
video without a physical reconnect. Wi-Fi is a strong primary-candidate
direction for portability and recoverable Range semantics, but it must first
earn that status with real throughput, permission, and interruption tests.

The raw IOUSBHost backend remains frozen as a reference backend, not removed.

## Tomorrow's manual test checklist

1. Reconnect/unlock Pixel and select **File Transfer / Android Auto**.
2. Run the three Track A commands above; keep `/tmp/photovault-libusb-test.jpg`.
3. Note `LIBUSB_MTP_*` output, file size, SHA-256, and whether the Pixel still
   works without reconnecting.
4. Install the APK: `adb install -r android-companion/build/photovault-companion-debug.apk`.
5. Open **PhotoVault Companion**, grant Photos and Videos permission, and keep
   its screen open on the same Wi-Fi as the Mac.
6. Copy the displayed URL and token into the three Track B commands above.
7. Run `list`; choose one JPEG `OBJECT_ID`; run `stream` and record bytes/time.
8. Repeat `stream` for two more photos without restarting the app.
9. If there is a safe 100 MB+ video, stream it and record elapsed time.
10. Send the exact outputs back; do not use external backup disks or delete
    phone media.

## Git and validation summary

Branch: `feature/android-source-macos`.

New source: libusb helper/build script, Android companion/build script,
desktop Wi-Fi source, CLI commands, and one automated Wi-Fi protocol test.

Validation: `PYTHONPATH=src python3 -m unittest discover -s tests -v` passed
61 tests with 4 optional PySide6 tests skipped. Both native libusb helper and
Android debug APK builds passed. Real-device tests are intentionally marked
NOT TESTED rather than inferred from build success.
