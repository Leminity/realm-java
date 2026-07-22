#!/usr/bin/env bash
# Modified by Leminity from the upstream Realm Java project.
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
  if ! is_post_review_allowed_path "$path"; then
    printf 'approved post-review path was rejected: %s\n' "$path" >&2
    exit 1
  fi
done < <(git diff-tree --no-commit-id --name-only -r "$EXPECTED_APPROVED_FORK_ROOT" HEAD)

for allowed in \
  'evidence/audit/g002-toolchain-final.md' \
  'evidence/audit/task-9-preflight.md' \
  'evidence/audit/g003-independent-build-recovery.md' \
  'tools/verify-g003-independent-builds.sh' \
  'tools/test-verify-g003-independent-builds.sh' \
  'tools/verify-g009-ac09-compatibility.py' \
  'tools/test-verify-g009-ac09-compatibility.py' \
  'evidence/g009/ac09/report.json'; do
  if ! is_baseline_allowed_path "$allowed"; then
    printf 'approved audit path was rejected: %s\n' "$allowed" >&2
    exit 1
  fi
done

for allowed in "${APPROVED_POST_REVIEW_PATHS[@]}"; do
  if ! is_post_review_allowed_path "$allowed"; then
    printf 'approved post-review path was rejected: %s\n' "$allowed" >&2
    exit 1
  fi
done

for allowed in \
  '.github/workflows/release.yml' \
  'tools/central-portal.py' \
  'tools/test-central-portal.py' \
  'tools/test-g014-release-binding.py'; do
  if ! is_post_review_allowed_path "$allowed"; then
    printf 'approved G014 remediation path was rejected: %s\n' "$allowed" >&2
    exit 1
  fi
done

for allowed in \
  'compatibility-fixtures/ac07-bidirectional/run-ac07.sh' \
  'compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh' \
  'tools/test-ac08-g011-parameterization.py'; do
  if ! is_post_review_allowed_path "$allowed"; then
    printf 'approved Task 8 remediation path was rejected: %s\n' "$allowed" >&2
    exit 1
  fi
done

mapfile -t actual_fork_modified < <(
  git diff-tree --no-commit-id --name-only -r --diff-filter=M \
    "$EXPECTED_COMMIT" "$EXPECTED_APPROVED_FORK_ROOT" | sort
)
mapfile -t expected_fork_modified < <(printf '%s\n' "${APPROVED_FORK_MODIFIED_PATHS[@]}" | sort)
if [[ "$(printf '%s\n' "${actual_fork_modified[@]}")" != \
      "$(printf '%s\n' "${expected_fork_modified[@]}")" ]]; then
  echo 'exact 37-path fork modification boundary differs' >&2
  exit 1
fi
[[ ${#actual_fork_modified[@]} -eq 37 ]]

for worker in worker1 worker2 worker3; do
  if ! is_post_review_allowed_path \
    ".omx/recovery/transactions/G013-independent-review-remediation-20260721T000000Z-$worker/PRE"; then
    printf '%s transaction evidence path was rejected\n' "$worker" >&2
    exit 1
  fi
done
if ! is_post_review_allowed_path \
  '.omx/recovery/transactions/G013-independent-review-trust-boundary-20260721T000000Z-worker1/PRE'; then
  printf 'worker1 trust-boundary transaction evidence path was rejected\n' >&2
  exit 1
fi
if ! is_post_review_allowed_path \
  '.omx/recovery/transactions/G013-reboot-safe-history-remediation-20260722T000000Z-worker1/PRE'; then
  printf 'worker1 reboot-safe history transaction evidence path was rejected\n' >&2
  exit 1
fi
for disallowed in \
  '.github/workflows/unreviewed.yml' \
  '.github/workflows/release-unreviewed.yml' \
  'compatibility-fixtures/ac07-bidirectional/unreviewed.sh' \
  'compatibility-fixtures/ac08-api37-ps16k-runtime/unreviewed.sh' \
  '.omx/recovery/transactions/G013-unrelated-worker1/PRE' \
  '.omx/recovery/transactions/G013-independent-review-trust-boundary-20260721T000000Z-worker2/PRE' \
  '.omx/recovery/transactions/G013-reboot-safe-history-remediation-20260722T000000Z-worker2/PRE' \
  'realm/realm-library/src/main/java/io/realm/Realm.java' \
  'tools/test-ac08-g011-unapproved.py' \
  'tools/unapproved-helper.sh'; do
  if is_post_review_allowed_path "$disallowed"; then
    printf 'unauthorized post-review path was accepted: %s\n' "$disallowed" >&2
    exit 1
  fi
done

for allowed in "${APPROVED_G003_PATHS[@]}"; do
  if ! is_baseline_allowed_path "$allowed"; then
    printf 'approved G003 path was rejected: %s\n' "$allowed" >&2
    exit 1
  fi
done

for disallowed in \
  'build.gradle.kts' \
  'evidence/g003/F056-unlinked.log' \
  'realm/src/main/java/io/realm/Realm.java' \
  'realm/realm-library/src/main/cpp/realm/unsafe.cpp' \
  'realm-transformer/src/main/kotlin/io/realm/transformer/Unapproved.kt' \
  'compatibility-fixtures/unapproved/app/src/main/java/Injected.java' \
  'evidence/toolchain/unapproved/README.md' \
  'evidence/audit/g003-unapproved.md' \
  'tools/verify-g004-unapproved.sh' \
  'tools/unapproved-helper.sh' \
  'unexpected-root-file.md'; do
  if is_baseline_allowed_path "$disallowed"; then
    printf 'unauthorized path was accepted: %s\n' "$disallowed" >&2
    exit 1
  fi
done

temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT
verify_recorded_baseline evidence/provenance/baseline.json
cp evidence/provenance/baseline.json "$temp_dir/mutated-baseline.json"
printf '\n' >> "$temp_dir/mutated-baseline.json"
if verify_recorded_baseline "$temp_dir/mutated-baseline.json"; then
  echo 'mutated immutable baseline manifest was accepted' >&2
  exit 1
fi

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

tools/verify-baseline.sh
echo 'baseline verifier regression tests: PASS'
