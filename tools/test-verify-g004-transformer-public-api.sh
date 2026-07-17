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

# Generated fixtures must resolve the fork coordinates from the caller-owned,
# isolated Maven repository rather than the retired io.realm group or ambient
# ~/.m2 state.
fixture="$temp_dir/generated-fixture"
staged_maven_repo="$temp_dir/maven-repository"
transformer_jar="$temp_dir/realm-transformer-test-version.jar"
transformer_version='test-version'
sdk_dir="$temp_dir/android-sdk"
mkdir -p "$staged_maven_repo" "$sdk_dir/platforms"
touch "$transformer_jar"
write_fixture "$fixture" application java
grep -Fq "maven { url = uri('$staged_maven_repo') }" "$fixture/settings.gradle"
grep -Fq "classpath 'io.github.leminity.realm:realm-annotations:$transformer_version'" "$fixture/build.gradle"
grep -Fq "implementation 'io.github.leminity.realm:realm-android-library:$transformer_version'" "$fixture/app/build.gradle"
if grep -R -Fq "io.realm:realm-" "$fixture"; then
  echo 'G004 fixture retained a retired io.realm coordinate' >&2
  exit 1
fi

# The isolated staging sequence must remain base-only. In particular, do not
# replace the final task with realm publishToMavenLocal, which also selects
# unsupported publication variants.
calls="$temp_dir/stage-calls.txt"
run_project_gradle() {
  printf '%s|%s' "$1" "$2" >> "$calls"
  shift 2
  printf '|%s\n' "$*" >> "$calls"
}
stage_fixture_dependencies
cat > "$temp_dir/expected-stage-calls.txt" <<'EOF'
annotations-local-stage|realm-annotations|publishToMavenLocal
transformer-local-stage|realm-transformer|publishToMavenLocal
build-transformer-local-stage|library-build-transformer|publishToMavenLocal
realm-base-local-stage|realm|:realm-library:publishBasePublicationToMavenLocal
EOF
cmp "$temp_dir/expected-stage-calls.txt" "$calls"
if grep -Eq '^realm-base-local-stage\|realm\|publishToMavenLocal$' "$calls"; then
  echo 'G004 staging selected the broad Realm publication graph' >&2
  exit 1
fi

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
