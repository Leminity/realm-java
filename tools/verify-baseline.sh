#!/usr/bin/env bash
# Validates the exact source and recursive-submodule provenance baseline.
set -euo pipefail

readonly EXPECTED_COMMIT=0ab8d6961afb038d0e0c69478de45dda3958d641
readonly EXPECTED_TAG=v10.19.0
readonly EXPECTED_CORE=5533505d18fda93a7a971d58a191db5005583c92
readonly EXPECTED_CATCH=3f0283de7a9c43200033da996ff9093be3ac84dc
readonly EXPECTED_SHA1=d9ae30f34095107ece9dceb224839f0dc2f9c1c7
readonly EXPECTED_SHA2=0e9aebf34101c6aa89355fd76ac9cd886735dee1
readonly REQUIRED_GRADLE_URL='https\://services.gradle.org/distributions/gradle-9.6.1-bin.zip'
readonly REQUIRED_GRADLE_SHA256=9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14
readonly -a APPROVED_WRAPPER_PATHS=(
  examples/gradle/wrapper/gradle-wrapper.properties
  gradle-plugin/gradle/wrapper/gradle-wrapper.properties
  gradle/wrapper/gradle-wrapper.properties
  library-benchmarks/gradle/wrapper/gradle-wrapper.properties
  library-build-transformer/gradle/wrapper/gradle-wrapper.properties
  realm-annotations/gradle/wrapper/gradle-wrapper.properties
  realm-transformer/gradle/wrapper/gradle-wrapper.properties
  realm/gradle/wrapper/gradle-wrapper.properties
)

is_baseline_allowed_path() {
  local path="$1"

  # These are deliberately exact G001/G002 non-production surfaces. Do not
  # replace them with parent-directory wildcards: fixture source is confined to
  # one isolated harness and evidence is confined to its recorded version/root.
  case "$path" in
    .gitignore|compatibility-change-ledger.md|production-diff-ledger.md|\
    evidence/provenance/*|\
    evidence/oracle/official-10.19.0/*|\
    evidence/toolchain/android17-wsl2/*|\
    evidence/toolchain/task-12-api37-runtime-audit/*|\
    evidence/audit/g002-toolchain-final.md|\
    evidence/audit/task-9-preflight.md|\
    compatibility-fixtures/official-10.19.0-generator/*|\
    tools/capture-baseline.py|tools/verify-baseline.sh|\
    tools/verify-release-tag.sh|tools/test-verify-release-tag.sh|\
    tools/bootstrap-wsl-android.sh|tools/verify-toolchain.sh|\
    tools/test-verify-baseline.sh|\
    examples/gradle/wrapper/gradle-wrapper.properties|\
    gradle-plugin/gradle/wrapper/gradle-wrapper.properties|\
    gradle/wrapper/gradle-wrapper.properties|\
    library-benchmarks/gradle/wrapper/gradle-wrapper.properties|\
    library-build-transformer/gradle/wrapper/gradle-wrapper.properties|\
    realm-annotations/gradle/wrapper/gradle-wrapper.properties|\
    realm-transformer/gradle/wrapper/gradle-wrapper.properties|\
    realm/gradle/wrapper/gradle-wrapper.properties)
      return 0
      ;;
  esac

  return 1
}

is_approved_wrapper_pin() {
  [[ "$1" == "$REQUIRED_GRADLE_URL" && "$2" == "$REQUIRED_GRADLE_SHA256" ]]
}

verify_approved_wrapper_pins() {
  local wrapper url sha

  for wrapper in "${APPROVED_WRAPPER_PATHS[@]}"; do
    url="$(sed -n 's/^distributionUrl=//p' "$wrapper")"
    sha="$(sed -n 's/^distributionSha256Sum=//p' "$wrapper")"
    if ! is_approved_wrapper_pin "$url" "$sha"; then
      printf 'unexpected Gradle wrapper pin in %s\n' "$wrapper" >&2
      return 1
    fi
  done
}

verify_baseline_capture() {
  local baseline="$1"
  local current="$2"

  python3 - "$baseline" "$current" <<'PY'
import json
import sys

baseline_path, current_path = sys.argv[1:]
with open(baseline_path, encoding="utf-8") as source:
    baseline = json.load(source)
with open(current_path, encoding="utf-8") as source:
    current = json.load(source)

# Wrapper URLs deliberately advance from the immutable v10.19.0 baseline to
# the exact G002 pins. Every other captured field must remain byte-for-value
# equivalent after JSON parsing.
baseline.pop("wrappers", None)
current.pop("wrappers", None)
if baseline != current:
    print("immutable baseline capture differs outside approved wrapper pins", file=sys.stderr)
    raise SystemExit(1)
PY
}

main() {
  local root path core
  local -a invalid_paths=()

  root="$(git rev-parse --show-toplevel)"
  cd "$root"

  [[ "$(git rev-parse "${EXPECTED_TAG}^{commit}")" == "$EXPECTED_COMMIT" ]]
  git merge-base --is-ancestor "$EXPECTED_COMMIT" HEAD
  [[ "$(git remote get-url upstream)" == "https://github.com/realm/realm-java.git" ]]
  [[ "$(git remote get-url origin)" == "https://github.com/Leminity/realm-java.git" ]]

  while IFS= read -r path; do
    is_baseline_allowed_path "$path" || invalid_paths+=("$path")
  done < <(git diff --name-only "$EXPECTED_COMMIT...HEAD")
  if ((${#invalid_paths[@]})); then
    printf 'non-baseline path(s) changed since %s:\n' "$EXPECTED_TAG" >&2
    printf '  %s\n' "${invalid_paths[@]}" >&2
    exit 1
  fi

  [[ "$(git -C realm/realm-library/src/main/cpp/realm-core rev-parse HEAD)" == "$EXPECTED_CORE" ]]
  core=realm/realm-library/src/main/cpp/realm-core
  [[ "$(git -C "$core/external/catch" rev-parse HEAD)" == "$EXPECTED_CATCH" ]]
  [[ "$(git -C "$core/src/external/sha-1" rev-parse HEAD)" == "$EXPECTED_SHA1" ]]
  [[ "$(git -C "$core/src/external/sha-2" rev-parse HEAD)" == "$EXPECTED_SHA2" ]]

  python3 tools/capture-baseline.py --output /tmp/realm-baseline-verify.json
  verify_baseline_capture evidence/provenance/baseline.json /tmp/realm-baseline-verify.json
  verify_approved_wrapper_pins
  rm -f /tmp/realm-baseline-verify.json
  tools/test-verify-release-tag.sh

  echo 'baseline provenance verification: PASS'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
