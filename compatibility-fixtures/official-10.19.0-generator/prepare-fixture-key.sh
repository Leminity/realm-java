#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
key=$(tr -d '\r\n' < "$project_dir/fixed-test-key.hex")
[[ "$key" =~ ^[0-9A-Fa-f]{128}$ ]] || { echo 'fixed-test-key.hex must contain exactly 128 hexadecimal characters' >&2; exit 2; }
printf 'export FIXTURE_KEY_HEX=%s\n' "$key"
printf 'FIXTURE_KEY_SHA256=%s\n' "$(printf '%s' "$key" | xxd -r -p | sha256sum | awk '{print $1}')"
printf '%s\n' 'This deterministic test-only oracle vector is retained for reproducible fork and wrong-key checks.'
