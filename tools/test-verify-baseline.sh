#!/usr/bin/env bash
# Regression coverage for the strict non-production allowlist in verify-baseline.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "$root"

# The verifier exposes this predicate so this test can exercise both the
# currently approved baseline delta and adversarial path candidates.
# shellcheck source=tools/verify-baseline.sh
source tools/verify-baseline.sh

while IFS= read -r path; do
  [[ -n "$path" ]] || continue
  if ! is_baseline_allowed_path "$path"; then
    printf 'approved baseline path was rejected: %s\n' "$path" >&2
    exit 1
  fi
done < <(git diff --name-only "$EXPECTED_COMMIT...HEAD")

for allowed in \
  'evidence/audit/g002-toolchain-final.md' \
  'evidence/audit/task-9-preflight.md' \
  'evidence/audit/g003-independent-build-recovery.md' \
  'tools/verify-g003-independent-builds.sh' \
  'tools/test-verify-g003-independent-builds.sh'; do
  if ! is_baseline_allowed_path "$allowed"; then
    printf 'approved audit path was rejected: %s\n' "$allowed" >&2
    exit 1
  fi
done

for disallowed in \
  'realm/src/main/java/io/realm/Realm.java' \
  'realm/realm-library/src/main/cpp/realm/unsafe.cpp' \
  'compatibility-fixtures/unapproved/app/src/main/java/Injected.java' \
  'evidence/toolchain/unapproved/README.md' \
  'evidence/audit/g003-unapproved.md' \
  'tools/unapproved-helper.sh' \
  'unexpected-root-file.md'; do
  if is_baseline_allowed_path "$disallowed"; then
    printf 'unauthorized path was accepted: %s\n' "$disallowed" >&2
    exit 1
  fi
done

temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT
python3 tools/capture-baseline.py --output "$temp_dir/current.json"

verify_baseline_capture evidence/provenance/baseline.json "$temp_dir/current.json"

if ! is_approved_wrapper_pin "$REQUIRED_GRADLE_URL" "$REQUIRED_GRADLE_SHA256"; then
  echo 'required Gradle 9.6.1 wrapper pin was rejected' >&2
  exit 1
fi
for invalid_pin in \
  'https\://services.gradle.org/distributions/gradle-7.5-all.zip|9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14' \
  'https\://services.gradle.org/distributions/gradle-9.6.1-bin.zip|0000000000000000000000000000000000000000000000000000000000000000'; do
  IFS='|' read -r url sha <<< "$invalid_pin"
  if is_approved_wrapper_pin "$url" "$sha"; then
    printf 'invalid wrapper pin was accepted: %s\n' "$invalid_pin" >&2
    exit 1
  fi
done

python3 - "$temp_dir/current.json" "$temp_dir/non-wrapper-mismatch.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    capture = json.load(source)
capture["source"]["commit"] = "0000000000000000000000000000000000000000"
with open(sys.argv[2], "w", encoding="utf-8") as target:
    json.dump(capture, target, sort_keys=True)
PY
if verify_baseline_capture evidence/provenance/baseline.json "$temp_dir/non-wrapper-mismatch.json"; then
  echo 'non-wrapper baseline mismatch was accepted' >&2
  exit 1
fi

tools/verify-baseline.sh
echo 'baseline verifier regression tests: PASS'
