#!/bin/zsh
set -euo pipefail
project_root=${0:A:h:h}
libusb_prefix=/opt/homebrew/opt/libusb
if [[ ! -f "$libusb_prefix/include/libusb-1.0/libusb.h" ]]; then
  print -u2 "libusb headers not found at $libusb_prefix; install Homebrew libusb first"
  exit 2
fi
mkdir -p "$project_root/native/macos/android_mtp_libusb"
clang -O2 -Wall -Wextra -Werror \
  -I"$libusb_prefix/include/libusb-1.0" \
  "$project_root/native/macos/android_mtp_libusb/main.c" \
  -L"$libusb_prefix/lib" -Wl,-rpath,"$libusb_prefix/lib" -lusb-1.0 \
  -o "$project_root/native/macos/android_mtp_libusb/photovault-android-libusb-mtp"
file "$project_root/native/macos/android_mtp_libusb/photovault-android-libusb-mtp"
