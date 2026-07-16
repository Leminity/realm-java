#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
sdk_root=${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}
adb="$sdk_root/platform-tools/adb"
aapt2="${AAPT2_OVERRIDE:-$sdk_root/build-tools/36.0.0/aapt2}"
export ANDROID_HOME="$sdk_root"
export ANDROID_SDK_ROOT="$sdk_root"
[[ -x "$aapt2" ]] || { echo "Missing compatible AAPT2 at $aapt2" >&2; exit 2; }
export ANDROID_AAPT2_FROM_MAVEN_OVERRIDE="$aapt2"
if [[ -z "${FIXTURE_KEY_HEX:-}" ]]; then
  FIXTURE_KEY_HEX=$(tr -d '\r\n' < "$project_dir/fixed-test-key.hex")
fi
[[ "$FIXTURE_KEY_HEX" =~ ^[0-9A-Fa-f]{128}$ ]] || { echo 'FIXTURE_KEY_HEX must be exactly 128 hexadecimal characters' >&2; exit 2; }
export FIXTURE_KEY_HEX
[[ -x "$adb" ]] || { echo "Missing adb at $adb" >&2; exit 2; }
serial=${ANDROID_SERIAL:-}
if [[ -z "$serial" ]]; then
  mapfile -t devices < <("$adb" devices | awk 'NR>1 && $2 == "device" {print $1}')
  (( ${#devices[@]} == 1 )) || { echo "Expected exactly one connected Android device/emulator; found ${#devices[@]}" >&2; exit 3; }
  serial=${devices[0]}
fi
"$adb" -s "$serial" get-state | grep -qx device || { echo "Android serial is not ready: $serial" >&2; exit 3; }
key_sha256=$(printf '%s' "$FIXTURE_KEY_HEX" | xxd -r -p | sha256sum | awk '{print $1}')
(cd "$project_dir" && ./gradlew --no-daemon -Pandroid.aapt2FromMavenOverride="$aapt2" connectedDebugAndroidTest)
rm -rf "$project_dir/generated"
mkdir -p "$project_dir/generated"
"$adb" -s "$serial" exec-out run-as io.realm.fixtureoracle sh -c \
  'cd files && tar -cf - official-10.19.0-oracle/official-10.19.0-plain.realm official-10.19.0-oracle/official-10.19.0-encrypted.realm official-10.19.0-oracle/fixture-manifest.json' | tar -xf - -C "$project_dir/generated"
python3 "$project_dir/verify-generated-fixtures.py" "$project_dir/generated/official-10.19.0-oracle" "$key_sha256"
