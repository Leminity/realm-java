#!/usr/bin/env bash
set -euo pipefail
key=$(openssl rand -hex 64)
printf 'export FIXTURE_KEY_HEX=%s\n' "$key"
printf 'FIXTURE_KEY_SHA256=%s\n' "$(printf '%s' "$key" | xxd -r -p | sha256sum | awk '{print $1}')"
printf '%s\n' 'Store the test-only key in an approved secret store; commit only its SHA-256 fingerprint.'
