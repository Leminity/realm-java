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
  'evidence/audit/task-9-preflight.md'; do
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
  'tools/unapproved-helper.sh' \
  'unexpected-root-file.md'; do
  if is_baseline_allowed_path "$disallowed"; then
    printf 'unauthorized path was accepted: %s\n' "$disallowed" >&2
    exit 1
  fi
done

tools/verify-baseline.sh
echo 'baseline verifier regression tests: PASS'
