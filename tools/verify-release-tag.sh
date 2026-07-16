#!/usr/bin/env bash
# Validates the only permitted immutable fork tag/version family.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <tag> <pom-version>" >&2
  exit 64
fi

tag=$1
pom_version=$2

if [[ ! $tag =~ ^v10\.19\.0-agp9\.[1-9][0-9]*$ ]]; then
  echo "invalid fork tag: $tag" >&2
  exit 1
fi

if [[ ${tag#v} != "$pom_version" ]]; then
  echo "tag/version mismatch: $tag != v$pom_version" >&2
  exit 1
fi

printf 'validated tag=%s pom_version=%s\n' "$tag" "$pom_version"
