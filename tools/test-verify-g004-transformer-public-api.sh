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

# Classified publication artifacts must not displace the exact primary JAR.
source "$verifier"
jar_dir="$temp_dir/transformer-jars"
version='test-version'
mkdir -p "$jar_dir"
touch "$jar_dir/realm-transformer-$version-javadoc.jar"
touch "$jar_dir/realm-transformer-$version-sources.jar"
touch "$jar_dir/realm-transformer-$version.jar"
selected_jar="$(select_primary_transformer_jar "$jar_dir" "$version")"
[[ "$selected_jar" == "$jar_dir/realm-transformer-$version.jar" ]] || {
  echo "G004 verifier selected a classified transformer JAR: $selected_jar" >&2
  exit 1
}

rm "$jar_dir/realm-transformer-$version.jar"
if (select_primary_transformer_jar "$jar_dir" "$version" >/dev/null 2>&1); then
  echo 'G004 verifier accepted a missing primary transformer JAR' >&2
  exit 1
fi

printf 'G004 transformer verifier regression tests: PASS\n'
