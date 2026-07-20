#!/usr/bin/env bash
# Build G008 local publication inputs only. This command has no upload,
# credential, cloud-storage, notification, or remote publication behavior.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
task="g008VerifyLocalStaging"

if [[ ${1:-} == "--signed-bundle" ]]; then
  task="g008Bundle"
elif [[ $# -ne 0 ]]; then
  echo "usage: $0 [--signed-bundle]" >&2
  exit 2
fi

exec "$root/gradlew" --no-daemon "$task"
