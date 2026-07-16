#!/usr/bin/env bash
set -euo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/verify-release-tag.sh"

"$script" v10.19.0-agp9.1 10.19.0-agp9.1
"$script" v10.19.0-agp9.27 10.19.0-agp9.27

for invalid in \
  '10.19.0-agp9.1 10.19.0-agp9.1' \
  'v10.19.0-agp9.0 10.19.0-agp9.0' \
  'v10.19.0-agp9.01 10.19.0-agp9.01' \
  'v10.19.0-agp9.1-extra 10.19.0-agp9.1-extra' \
  'v10.19.1-agp9.1 10.19.1-agp9.1' \
  'v10.19.0-agp9.1 10.19.0-agp9.2'; do
  # shellcheck disable=SC2086 -- each table row intentionally supplies two arguments.
  if $script $invalid >/dev/null 2>&1; then
    echo "unexpectedly accepted: $invalid" >&2
    exit 1
  fi
done

echo 'release-tag parser tests: PASS'
