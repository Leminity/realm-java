#!/usr/bin/env bash
# Installs the exact Android SDK packages required by the Realm Java AGP 9 toolchain.
set -euo pipefail

readonly CMDLINE_TOOLS_REV=14742923
readonly CMDLINE_TOOLS_SHA1=48833c34b761c10cb20bcd16582129395d121b27
readonly CMDLINE_TOOLS_URL="https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS_REV}_latest.zip"
readonly API37_16K_IMAGE="system-images;android-37.0;google_apis_ps16k;x86_64"
readonly CMAKE_VERSION=3.27.7
readonly CMAKE_ARCHIVE="cmake-${CMAKE_VERSION}-linux-x86_64.tar.gz"
readonly CMAKE_URL="https://cmake.org/files/v3.27/${CMAKE_ARCHIVE}"
readonly CMAKE_SHA256=a8c92ecb139bcc7a1f92a8108179bd1d021bdb158a5ee759cba6d60010b83ae9
readonly REQUIRED_PACKAGES=(
  "platform-tools"
  "emulator"
  # Google's current API 37 package is named android-37.0; it is API level 37,
  # not a lower compile target.
  "platforms;android-37.0"
  "build-tools;36.0.0"
  "ndk;29.0.14206865"
)

sdk_root="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Android/Sdk}}"
evidence_dir="${TOOLCHAIN_EVIDENCE_DIR:-evidence/toolchain/android17-wsl2}"

if [[ $# -gt 0 ]]; then
  case "$1" in
    --sdk-root) sdk_root=$2; shift 2 ;;
    --evidence-dir) evidence_dir=$2; shift 2 ;;
    *) echo "usage: $0 [--sdk-root PATH] [--evidence-dir PATH]" >&2; exit 64 ;;
  esac
fi

mkdir -p "$sdk_root" "$evidence_dir"
archive="$sdk_root/.commandlinetools-linux-${CMDLINE_TOOLS_REV}.zip"
sdkmanager="$sdk_root/cmdline-tools/latest/bin/sdkmanager"

if [[ ! -x "$sdkmanager" ]]; then
  curl --fail --location --retry 3 --output "$archive" "$CMDLINE_TOOLS_URL"
  printf '%s  %s\n' "$CMDLINE_TOOLS_SHA1" "$archive" | sha1sum --check --status
  printf '%s\n' "$CMDLINE_TOOLS_SHA1  commandlinetools-linux-${CMDLINE_TOOLS_REV}_latest.zip" > "$evidence_dir/commandline-tools.sha1"
  sha256sum "$archive" > "$evidence_dir/commandline-tools.sha256"

  staging=$(mktemp -d)
  trap 'rm -rf "$staging"' EXIT
  unzip -q "$archive" -d "$staging"
  rm -rf "$sdk_root/cmdline-tools/latest"
  mkdir -p "$sdk_root/cmdline-tools"
  mv "$staging/cmdline-tools" "$sdk_root/cmdline-tools/latest"
fi

export ANDROID_SDK_ROOT="$sdk_root"
export ANDROID_HOME="$sdk_root"
export PATH="$sdk_root/cmdline-tools/latest/bin:$sdk_root/platform-tools:$sdk_root/emulator:$PATH"

java -version > "$evidence_dir/java-version.txt" 2>&1
# sdkmanager closes stdin once all licenses are accepted, which makes `yes` exit
# with SIGPIPE. Preserve the sdkmanager result instead of failing under pipefail.
set +o pipefail
yes | "$sdkmanager" --sdk_root="$sdk_root" --licenses > "$evidence_dir/sdkmanager-licenses.txt"
license_status=${PIPESTATUS[1]}
set -o pipefail
[[ "$license_status" -eq 0 ]]
"$sdkmanager" --sdk_root="$sdk_root" "${REQUIRED_PACKAGES[@]}" | tee "$evidence_dir/sdkmanager-install.txt"
"$sdkmanager" --sdk_root="$sdk_root" --list > "$evidence_dir/sdkmanager-list.txt"

# Google no longer publishes cmake;3.27.7 through sdkmanager. Provision the
# exact upstream Kitware binary into the standard Android SDK side-by-side path
# and retain its official SHA-256 in the evidence manifest.
if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "CMake ${CMAKE_VERSION} bootstrap currently supports WSL2 x86_64 only" >&2
  exit 1
fi
cmake_dir="$sdk_root/cmake/$CMAKE_VERSION"
cmake_archive="$sdk_root/.${CMAKE_ARCHIVE}"
if [[ ! -f "$cmake_archive" ]]; then
  curl --fail --location --retry 3 --output "$cmake_archive" "$CMAKE_URL"
fi
printf '%s  %s\n' "$CMAKE_SHA256" "$cmake_archive" | sha256sum --check --status
sha256sum "$cmake_archive" > "$evidence_dir/cmake-${CMAKE_VERSION}-archive.sha256"
cmake_ready=false
if [[ -x "$cmake_dir/bin/cmake" ]] && "$cmake_dir/bin/cmake" --version | head -1 | grep -Fqx "cmake version $CMAKE_VERSION"; then
  cmake_ready=true
fi
if [[ "$cmake_ready" != true ]]; then
  cmake_staging=$(mktemp -d)
  tar -xzf "$cmake_archive" -C "$cmake_staging"
  rm -rf "$cmake_dir"
  mkdir -p "$(dirname "$cmake_dir")"
  mv "$cmake_staging/cmake-${CMAKE_VERSION}-linux-x86_64" "$cmake_dir"
  rm -rf "$cmake_staging"
fi
printf '%s  .%s\n' "$CMAKE_SHA256" "$CMAKE_ARCHIVE" > "$evidence_dir/cmake-${CMAKE_VERSION}.sha256"
printf '%s\n' "$CMAKE_URL" > "$evidence_dir/cmake-${CMAKE_VERSION}-source.txt"
"$cmake_dir/bin/cmake" --version > "$evidence_dir/cmake-${CMAKE_VERSION}-version.txt"

# The configured Google repository advertises this exact API 37, 16 KiB image.
grep -F "$API37_16K_IMAGE" "$evidence_dir/sdkmanager-list.txt" \
  > "$evidence_dir/api37-16k-system-images.txt" || true
if [[ -s "$evidence_dir/api37-16k-system-images.txt" ]]; then
  "$sdkmanager" --sdk_root="$sdk_root" "$API37_16K_IMAGE" | tee "$evidence_dir/api37-16k-system-image-install.txt"
  printf 'installed=%s\n' "$API37_16K_IMAGE" > "$evidence_dir/api37-16k-runtime-status.txt"
else
  printf 'BLOCKED: configured Google repository does not advertise %s in sdkmanager --list output.\n' "$API37_16K_IMAGE" \
    > "$evidence_dir/api37-16k-runtime-status.txt"
fi

"$(dirname "$0")/verify-toolchain.sh" --sdk-root "$sdk_root" --evidence-dir "$evidence_dir"
