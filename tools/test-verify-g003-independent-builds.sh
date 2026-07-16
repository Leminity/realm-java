#!/usr/bin/env bash
# Regression checks for the G003 independent-build verifier itself.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
verifier="$root/tools/verify-g003-independent-builds.sh"

temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT

bash -n "$verifier"
"$verifier" --help >/dev/null

cat > "$temp_dir/allowed.log" <<'LOG'
> Task :realm-annotations:generatePomFileForRealmPublication
BUILD SUCCESSFUL
LOG
"$verifier" --check-log "$temp_dir/allowed.log"

for forbidden in \
  'https://static.realm.io/downloads/core.zip' \
  's3://realm-ci-artifacts/maven/releases/' \
  'publishToSonatype' \
  '> Task :examples:assembleDebug' \
  '> Task :realm-library:compileBaseObjectServerDebugSources' \
  '> Task :realm-library:syncIntegrationTest'; do
  printf '%s\n' "$forbidden" > "$temp_dir/forbidden.log"
  if "$verifier" --check-log "$temp_dir/forbidden.log" >/dev/null 2>&1; then
    printf 'forbidden activity was accepted: %s\n' "$forbidden" >&2
    exit 1
  fi
done

printf 'G003 independent-build verifier regression tests: PASS\n'
