#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
sdk_root=${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}
adb="$sdk_root/platform-tools/adb"
: "${FIXTURE_KEY_HEX:?Run eval \"$(./prepare-fixture-key.sh | head -1)\" or inject a 64-byte test-only key}"
[[ "$FIXTURE_KEY_HEX" =~ ^[0-9A-Fa-f]{128}$ ]] || { echo 'FIXTURE_KEY_HEX must be exactly 128 hexadecimal characters' >&2; exit 2; }
[[ -x "$adb" ]] || { echo "Missing adb at $adb" >&2; exit 2; }
mapfile -t devices < <("$adb" devices | awk 'NR>1 && $2 == "device" {print $1}')
(( ${#devices[@]} == 1 )) || { echo "Expected exactly one connected Android device/emulator; found ${#devices[@]}" >&2; exit 3; }
key_sha256=$(printf '%s' "$FIXTURE_KEY_HEX" | xxd -r -p | sha256sum | awk '{print $1}')
(cd "$project_dir" && ./gradlew --no-daemon connectedDebugAndroidTest -PfixtureKeyHex="$FIXTURE_KEY_HEX")
remote="/sdcard/Android/data/io.realm.fixtureoracle/files/official-10.19.0-oracle"
rm -rf "$project_dir/generated"
mkdir -p "$project_dir/generated"
"$adb" pull "$remote" "$project_dir/generated"
python3 "$project_dir/verify-generated-fixtures.py" "$project_dir/generated/official-10.19.0-oracle" "$key_sha256"
