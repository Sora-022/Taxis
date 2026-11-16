#!/usr/bin/env bash
# Rebuilds taxis-launcher.apk from source.
# Needs: JDK, aapt, apksigner, zipalign, dx, android.jar (API 23)
#   Ubuntu: sudo apt install default-jdk-headless aapt apksigner zipalign dalvik-exchange android-sdk-platform-23
set -euo pipefail
cd "$(dirname "$0")"
AJAR=${ANDROID_JAR:-/usr/lib/android-sdk/platforms/android-23/android.jar}
DX=${DX:-/usr/lib/android-sdk/build-tools/debian/dx}
KEYSTORE=${TAXIS_KEYSTORE:-"$HOME/.taxis-signing/taxis-release.keystore"}
: "${TAXIS_KEYSTORE_PASS:?Set TAXIS_KEYSTORE_PASS before building}"
OUT=build; rm -rf "$OUT"; mkdir -p "$OUT/classes" "$(dirname "$KEYSTORE")"
javac --release 8 -Xlint:-options -cp "$AJAR" -d "$OUT/classes" $(find src -name '*.java')
"$DX" --dex --output="$OUT/classes.dex" "$OUT/classes"
aapt package -f -M AndroidManifest.xml -S res -I "$AJAR" -F "$OUT/unsigned.apk"
( cd "$OUT" && aapt add unsigned.apk classes.dex >/dev/null )
zipalign -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
[ -f "$KEYSTORE" ] || keytool -genkeypair -keystore "$KEYSTORE" -storepass "$TAXIS_KEYSTORE_PASS" -keypass "$TAXIS_KEYSTORE_PASS" \
  -alias taxis -keyalg RSA -keysize 2048 -validity 36500 -dname "CN=Taxis Launcher"
apksigner sign --ks "$KEYSTORE" --ks-pass env:TAXIS_KEYSTORE_PASS --key-pass env:TAXIS_KEYSTORE_PASS --out taxis-launcher.apk "$OUT/aligned.apk"
apksigner verify taxis-launcher.apk && echo "built taxis-launcher.apk ($(stat -c %s taxis-launcher.apk) bytes)"
