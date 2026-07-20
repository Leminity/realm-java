#!/usr/bin/env bash
# Verify the published Realm Android AAR's exact JNI ABI set and ELF LOAD alignment.
set -euo pipefail

EXPECTED_ABIS=(armeabi-v7a arm64-v8a x86_64)
NDK_VERSION=29.0.14206865

usage() {
  cat >&2 <<'USAGE'
usage: g011-verify-native-elf.sh (--aar <realm-android-library.aar> | --bundle <central-bundle.zip>) \
  --evidence-dir <dir> [--ndk-root <sdk/ndk/29.0.14206865>] [--llvm-readelf <path>]
USAGE
  exit 64
}
fail() { printf 'G011 native ELF FAIL: %s\n' "$*" >&2; return 1; }
require_value() { [[ $# -ge 2 && -n $2 ]] || usage; }

aar=''
bundle=''
evidence=''
ndk_root=''
llvm_readelf=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --aar) require_value "$@"; aar=$2; shift 2 ;;
    --bundle) require_value "$@"; bundle=$2; shift 2 ;;
    --evidence-dir) require_value "$@"; evidence=$2; shift 2 ;;
    --ndk-root) require_value "$@"; ndk_root=$2; shift 2 ;;
    --llvm-readelf) require_value "$@"; llvm_readelf=$2; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done
[[ -n $evidence && ( -n $aar || -n $bundle ) && ! ( -n $aar && -n $bundle ) ]] || usage
[[ -z $aar || -f $aar ]] || { printf 'missing AAR: %s\n' "$aar" >&2; exit 1; }
[[ -z $bundle || -f $bundle ]] || { printf 'missing bundle: %s\n' "$bundle" >&2; exit 1; }

host_tag=''
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) host_tag=linux-x86_64 ;;
  Darwin-arm64) host_tag=darwin-arm64 ;;
  Darwin-x86_64) host_tag=darwin-x86_64 ;;
  *) printf 'unsupported host for NDK llvm-readelf: %s-%s\n' "$(uname -s)" "$(uname -m)" >&2; exit 1 ;;
esac
if [[ -z $llvm_readelf ]]; then
  if [[ -z $ndk_root ]]; then
    sdk_root=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}
    [[ -n $sdk_root ]] || { printf 'set ANDROID_SDK_ROOT/ANDROID_HOME or pass --ndk-root\n' >&2; exit 1; }
    ndk_root="$sdk_root/ndk/$NDK_VERSION"
  fi
  [[ $ndk_root == */ndk/$NDK_VERSION || $ndk_root == *"/$NDK_VERSION" ]] || { printf 'expected NDK %s, got %s\n' "$NDK_VERSION" "$ndk_root" >&2; exit 1; }
  llvm_readelf="$ndk_root/toolchains/llvm/prebuilt/$host_tag/bin/llvm-readelf"
fi
[[ -x $llvm_readelf ]] || { printf 'missing executable llvm-readelf: %s\n' "$llvm_readelf" >&2; exit 1; }

prepare_fresh_evidence() {
  local directory="$1"
  if [[ -e $directory && ! -d $directory ]]; then
    printf 'evidence path is not a directory: %s\n' "$directory" >&2
    exit 1
  fi
  if [[ -d $directory ]] && find "$directory" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    printf 'evidence directory must be empty: %s\n' "$directory" >&2
    exit 1
  fi
  mkdir -p "$directory"
}

prepare_fresh_evidence "$evidence"
mkdir "$evidence/raw"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
if [[ -n $bundle ]]; then
  mapfile -t aar_entries < <(unzip -Z1 "$bundle" | grep -E '(^|/)realm-android-library-[^/]+\.aar$' || true)
  [[ ${#aar_entries[@]} -eq 1 ]] || { printf 'bundle must contain exactly one realm-android-library AAR, got %s\n' "${#aar_entries[@]}" >&2; exit 1; }
  aar="$work/realm-android-library.aar"
  unzip -p "$bundle" "${aar_entries[0]}" > "$aar"
fi

report="$evidence/report.txt"
status=0
{
  printf 'tool=g011-verify-native-elf\n'
  printf 'ndk_version=%s\n' "$NDK_VERSION"
  printf 'llvm_readelf=%s\n' "$llvm_readelf"
  printf 'aar=%s\n' "$aar"
  printf 'aar_sha256=%s\n' "$(sha256sum "$aar" | awk '{print $1}')"
  printf 'expected_abis=%s\n' "${EXPECTED_ABIS[*]}"
} > "$report"

mapfile -t entries < <(unzip -Z1 "$aar")
mapfile -t jni_entries < <(printf '%s\n' "${entries[@]}" | grep -E '^jni/[^/]+/.+\.so$' || true)
if [[ ${#jni_entries[@]} -eq 0 ]]; then
  printf 'FAIL no JNI .so entries\n' >> "$report"
  status=1
fi
mapfile -t actual_abis < <(printf '%s\n' "${jni_entries[@]}" | sed -E 's#^jni/([^/]+)/.*#\1#' | sort -u)
expected_join=$(printf '%s\n' "${EXPECTED_ABIS[@]}" | sort)
actual_join=$(printf '%s\n' "${actual_abis[@]:-}" | sort)
if [[ $actual_join != "$expected_join" ]]; then
  printf 'FAIL ABI set expected=[%s] actual=[%s]; x86 is forbidden\n' \
    "$(tr '\n' ' ' <<< "$expected_join")" "$(tr '\n' ' ' <<< "$actual_join")" >> "$report"
  status=1
else
  printf 'ABI_SET=PASS\n' >> "$report"
fi

for entry in "${jni_entries[@]}"; do
  abi=${entry#jni/}; abi=${abi%%/*}
  safe=$(printf '%s' "$entry" | tr '/ ' '__')
  raw="$evidence/raw/${safe}.readelf.txt"
  extracted="$work/$safe"
  unzip -p "$aar" "$entry" > "$extracted"
  if ! "$llvm_readelf" -lW "$extracted" > "$raw" 2>&1; then
    printf 'FAIL readelf execution entry=%s\n' "$entry" >> "$report"
    status=1
    continue
  fi
  mapfile -t aligns < <(awk '$1 == "LOAD" { print $NF }' "$raw")
  if [[ ${#aligns[@]} -eq 0 ]]; then
    printf 'FAIL no LOAD segments entry=%s\n' "$entry" >> "$report"
    status=1
    continue
  fi
  entry_status=PASS
  for align in "${aligns[@]}"; do
    if [[ ! $align =~ ^0[xX][0-9A-Fa-f]+$ ]] || (( align < 0x4000 )); then
      printf 'FAIL LOAD alignment entry=%s align=%s required>=0x4000\n' "$entry" "$align" >> "$report"
      entry_status=FAIL
      status=1
    fi
  done
  printf 'entry=%s abi=%s load_alignment=%s status=%s\n' "$entry" "$abi" "${aligns[*]}" "$entry_status" >> "$report"
done
if [[ $status -eq 0 ]]; then
  printf 'RESULT=PASS\n' >> "$report"
else
  printf 'RESULT=FAIL\n' >> "$report"
fi
write_checksums() {
  local manifest_tmp="$evidence/.SHA256SUMS.tmp"
  local verify_tmp="$evidence/.checksum-verify.tmp"
  (
    cd "$evidence"
    LC_ALL=C find . -type f \
      ! -name SHA256SUMS ! -name checksum-verify.log \
      ! -name .SHA256SUMS.tmp ! -name .checksum-verify.tmp \
      -printf '%P\0' | LC_ALL=C sort -z | xargs -0 sha256sum
  ) > "$manifest_tmp"
  mv -f "$manifest_tmp" "$evidence/SHA256SUMS"
  if (cd "$evidence" && sha256sum -c SHA256SUMS) > "$verify_tmp"; then
    mv -f "$verify_tmp" "$evidence/checksum-verify.log"
  else
    mv -f "$verify_tmp" "$evidence/checksum-verify.log"
    return 1
  fi
}
write_checksums
exit "$status"
