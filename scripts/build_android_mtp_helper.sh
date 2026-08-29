#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")/.."
SDKROOT="$(xcrun --sdk macosx --show-sdk-path)"
mkdir -p native/macos/android_mtp
clang -fobjc-arc -O2 -isysroot "$SDKROOT" native/macos/android_mtp/main.m \
  -framework Foundation -framework IOKit -framework IOUSBHost -framework Security \
  -o native/macos/android_mtp/photovault-android-mtp
clang -fobjc-arc -O2 -isysroot "$SDKROOT" tests/native/test_optional_payload.m \
  -framework Foundation -o /tmp/photovault-optional-payload-test
/tmp/photovault-optional-payload-test
file native/macos/android_mtp/photovault-android-mtp
