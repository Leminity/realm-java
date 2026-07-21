#!/usr/bin/env bash
set -euo pipefail
git apply --check "$(dirname "$0")/ROLLBACK.patch"
git apply "$(dirname "$0")/ROLLBACK.patch"
