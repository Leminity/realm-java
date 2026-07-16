#!/usr/bin/env bash
# Validates the exact source and recursive-submodule provenance baseline.
set -euo pipefail

readonly EXPECTED_COMMIT=0ab8d6961afb038d0e0c69478de45dda3958d641
readonly EXPECTED_TAG=v10.19.0
readonly EXPECTED_CORE=5533505d18fda93a7a971d58a191db5005583c92
readonly EXPECTED_CATCH=3f0283de7a9c43200033da996ff9093be3ac84dc
readonly EXPECTED_SHA1=d9ae30f34095107ece9dceb224839f0dc2f9c1c7
readonly EXPECTED_SHA2=0e9aebf34101c6aa89355fd76ac9cd886735dee1

root="$(git rev-parse --show-toplevel)"
cd "$root"

[[ "$(git rev-parse "${EXPECTED_TAG}^{commit}")" == "$EXPECTED_COMMIT" ]]
git merge-base --is-ancestor "$EXPECTED_COMMIT" HEAD
[[ "$(git remote get-url upstream)" == "https://github.com/realm/realm-java.git" ]]
[[ "$(git remote get-url origin)" == "https://github.com/Leminity/realm-java.git" ]]

# Baseline evidence may be committed after v10.19.0, but it may never conceal a
# production change. Oracle/fixture evidence is explicitly non-production.
invalid_paths=()
while IFS= read -r path; do
  case "$path" in
    .gitignore|compatibility-change-ledger.md|production-diff-ledger.md|\
    evidence/provenance/*|evidence/oracle/*|compatibility-fixtures/*|\
    tools/capture-baseline.py|tools/verify-baseline.sh|\
    tools/verify-release-tag.sh|tools/test-verify-release-tag.sh)
      ;;
    *) invalid_paths+=("$path") ;;
  esac
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
cmp -s /tmp/realm-baseline-verify.json evidence/provenance/baseline.json
rm -f /tmp/realm-baseline-verify.json
tools/test-verify-release-tag.sh

echo 'baseline provenance verification: PASS'
