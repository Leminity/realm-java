#!/usr/bin/env bash
# This historical script used the retired Maven Central upload/release path.
# Releases are intentionally possible only through the reviewer-gated Portal
# workflow, which binds the tag, Core gitlink, policy audit, and consumers.
set -euo pipefail

echo 'Legacy release is disabled. Use the Protected Maven Central release GitHub workflow.' >&2
exit 64
