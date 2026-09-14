# Android macOS packaging

The optional Android source requires the native arm64 helper at
native/macos/android_mtp/photovault-android-mtp. The helper is built with
scripts/build_android_mtp_helper.sh and is included in macOS PyInstaller
builds when present.

Development and packaged paths are both supported by the CLI helper lookup.
The helper is not included in Windows builds and Android support reports
unavailable there.

Before release, validate on a clean macOS machine:

1. helper architecture and executable permission;
2. Python can locate the bundled helper;
3. code signing covers the helper;
4. notarization accepts the helper;
5. the chosen distribution model permits unsandboxed IOUSBHost access.

The current hardware proof is an unsandboxed normal-user process. App Sandbox,
entitlements, signing and notarization are not claimed complete by this
development integration.
