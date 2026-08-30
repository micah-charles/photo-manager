#!/bin/zsh
set -euo pipefail
project_root=${0:A:h:h}
sdk_root=${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}
build_tools="$sdk_root/build-tools/35.0.0"
platform="$sdk_root/platforms/android-35/android.jar"
source_root="$project_root/android-companion"
out="$source_root/build"
for tool in "$build_tools/aapt2" "$build_tools/d8" "$build_tools/zipalign" "$build_tools/apksigner" "$platform"; do
  [[ -e "$tool" ]] || { print -u2 "missing Android SDK component: $tool"; exit 2; }
done
rm -rf "$out"
mkdir -p "$out/classes" "$out/res"
"$build_tools/aapt2" compile --dir "$source_root/res" -o "$out/res/resources.zip"
"$build_tools/aapt2" link -I "$platform" --manifest "$source_root/AndroidManifest.xml" --min-sdk-version 29 --target-sdk-version 35 -o "$out/unsigned.apk" "$out/res/resources.zip"
javac -source 8 -target 8 -bootclasspath "$platform" -d "$out/classes" $(find "$source_root/src" -name '*.java' | sort)
jar -cf "$out/classes.jar" -C "$out/classes" .
mkdir -p "$out/dex"
"$build_tools/d8" --lib "$platform" --min-api 29 --output "$out/dex" "$out/classes.jar"
(cd "$out/dex" && zip -q -j "$out/unsigned.apk" classes.dex)
"$build_tools/zipalign" -f 4 "$out/unsigned.apk" "$out/aligned.apk"
keystore="$out/debug.keystore"
keytool -genkeypair -keystore "$keystore" -storepass android -keypass android -alias androiddebugkey -dname 'CN=Android Debug,O=PhotoVault,C=GB' -keyalg RSA -keysize 2048 -validity 10000 >/dev/null 2>&1
"$build_tools/apksigner" sign --ks "$keystore" --ks-pass pass:android --key-pass pass:android --out "$out/photovault-companion-debug.apk" "$out/aligned.apk"
"$build_tools/apksigner" verify "$out/photovault-companion-debug.apk"
ls -lh "$out/photovault-companion-debug.apk"
