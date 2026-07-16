#!/usr/bin/env bash
# Regression checks for the G004 transformer public-API verifier itself.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
verifier="$root/tools/verify-g004-transformer-public-api.sh"
temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT

bash -n "$verifier"
"$verifier"

# A copied source tree that reintroduces the old internal API must be rejected.
mkdir -p "$temp_dir/realm-transformer/src/main/kotlin/io/realm/transformer/ext"
cp "$root/realm-transformer/src/main/kotlin/io/realm/transformer/ext/ProjectExt.kt" \
   "$temp_dir/realm-transformer/src/main/kotlin/io/realm/transformer/ext/"
cp "$root/realm-transformer/src/main/kotlin/io/realm/transformer/RealmTransformer.kt" \
   "$temp_dir/realm-transformer/src/main/kotlin/io/realm/transformer/"
sed -i 's/import com.android.build.api.dsl.ApplicationExtension/import com.android.build.gradle.BaseExtension/' \
  "$temp_dir/realm-transformer/src/main/kotlin/io/realm/transformer/ext/ProjectExt.kt"

if ROOT_OVERRIDE="$temp_dir" "$verifier" >/dev/null 2>&1; then
  echo 'G004 verifier accepted a reintroduced BaseExtension import' >&2
  exit 1
fi

printf 'G004 transformer verifier regression tests: PASS\n'
