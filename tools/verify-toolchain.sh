#!/usr/bin/env bash
# Produces a reproducible diagnostic manifest for the pinned AGP 9 Android toolchain.
set -euo pipefail

readonly EXPECTED_GRADLE_SHA256=9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14
readonly API37_16K_IMAGE_DIR="system-images/android-37.0/google_apis_ps16k/x86_64"
readonly WRAPPERS=(
  gradle/wrapper/gradle-wrapper.properties
  examples/gradle/wrapper/gradle-wrapper.properties
  gradle-plugin/gradle/wrapper/gradle-wrapper.properties
  library-benchmarks/gradle/wrapper/gradle-wrapper.properties
  library-build-transformer/gradle/wrapper/gradle-wrapper.properties
  realm/gradle/wrapper/gradle-wrapper.properties
  realm-annotations/gradle/wrapper/gradle-wrapper.properties
  realm-transformer/gradle/wrapper/gradle-wrapper.properties
)

sdk_root="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Android/Sdk}}"
evidence_dir="${TOOLCHAIN_EVIDENCE_DIR:-evidence/toolchain/android17-wsl2}"
emulator_runtime_lib_dir="${EMULATOR_RUNTIME_LIB_DIR:-$HOME/.local/realm-emulator-libs/root/usr/lib/x86_64-linux-gnu}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sdk-root) sdk_root=$2; shift 2 ;;
    --evidence-dir) evidence_dir=$2; shift 2 ;;
    *) echo "usage: $0 [--sdk-root PATH] [--evidence-dir PATH]" >&2; exit 64 ;;
  esac
done

sdkmanager="$sdk_root/cmdline-tools/latest/bin/sdkmanager"
mkdir -p "$evidence_dir"

# WSL hosts without the optional libpulse0 package can keep this unprivileged
# extracted runtime under ~/.local; use it when present so `emulator -version`
# verifies the installed emulator rather than failing at dynamic linking.
if [[ -d "$emulator_runtime_lib_dir" ]]; then
  export LD_LIBRARY_PATH="$emulator_runtime_lib_dir:$emulator_runtime_lib_dir/pulseaudio${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

{
  echo "sdk_root=$sdk_root"
  echo "emulator_runtime_lib_dir=$emulator_runtime_lib_dir"
  uname -a
  java -version 2>&1
  javac -version 2>&1
  "$sdk_root/cmake/3.27.7/bin/cmake" --version
  "$sdkmanager" --version
  "$sdk_root/platform-tools/adb" version
  "$sdk_root/emulator/emulator" -version
} > "$evidence_dir/environment-diagnostics.txt"

for path in \
  "$sdkmanager" \
  "$sdk_root/platform-tools/adb" \
  "$sdk_root/emulator/emulator" \
  "$sdk_root/platforms/android-37.0" \
  "$sdk_root/build-tools/36.0.0" \
  "$sdk_root/ndk/29.0.14206865" \
  "$sdk_root/cmake/3.27.7" \
  "$sdk_root/$API37_16K_IMAGE_DIR"; do
  [[ -e "$path" ]] || { echo "missing required toolchain path: $path" >&2; exit 1; }
done

"$sdk_root/cmake/3.27.7/bin/cmake" --version | head -1 | grep -Fqx 'cmake version 3.27.7'

for wrapper in "${WRAPPERS[@]}"; do
  grep -Fqx 'distributionUrl=https\://services.gradle.org/distributions/gradle-9.6.1-bin.zip' "$wrapper"
  grep -Fqx "distributionSha256Sum=$EXPECTED_GRADLE_SHA256" "$wrapper"
done

"$sdkmanager" --sdk_root="$sdk_root" --list > "$evidence_dir/sdkmanager-list-verified.txt"
printf 'toolchain verification: PASS\n' | tee "$evidence_dir/verification.txt"
