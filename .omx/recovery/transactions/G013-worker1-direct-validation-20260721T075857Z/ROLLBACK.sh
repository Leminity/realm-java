#!/usr/bin/env bash
set -euo pipefail
root=$(git rev-parse --show-toplevel)
git -C "$root" restore --source="9b952eb0c55c280128a9fee910274b6f906fa051" -- tools/central-portal.py tools/test-central-portal.py
printf 'restored worker-1 owned files from %s\n' "9b952eb0c55c280128a9fee910274b6f906fa051"
