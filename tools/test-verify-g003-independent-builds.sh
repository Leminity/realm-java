#!/usr/bin/env bash
# Regression checks for the G003 independent-build verifier itself.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
verifier="$root/tools/verify-g003-independent-builds.sh"

temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT

bash -n "$verifier"
"$verifier" --help >/dev/null

cat > "$temp_dir/allowed.log" <<'LOG'
> Task :realm-annotations:generatePomFileForRealmPublication
ObjectServer source remains outside the supported release graph.
BUILD SUCCESSFUL
LOG
"$verifier" --check-log "$temp_dir/allowed.log"

for forbidden in \
  'https://static.realm.io/downloads/core.zip' \
  's3://realm-ci-artifacts/maven/releases/' \
  '> Task :realm:publishToSonatype' \
  '> Task :examples:assembleDebug' \
  '> Task :realm-library:compileBaseObjectServerDebugSources' \
  '> Task :realm-library:syncIntegrationTest'; do
  printf '%s\n' "$forbidden" > "$temp_dir/forbidden.log"
  if "$verifier" --check-log "$temp_dir/forbidden.log" >/dev/null 2>&1; then
    printf 'forbidden activity was accepted: %s\n' "$forbidden" >&2
    exit 1
  fi
done

# Comments documenting the migration must not trigger the Kotlin-plugin gate,
# but an actual plugin application still must. Use an archived fixture so this
# exercises the canonical verifier against a complete static source tree.
comment_fixture_root="$temp_dir/comment-fixture-root"
mkdir -p "$comment_fixture_root"
git -C "$root" archive --format=tar HEAD | tar -xf - -C "$comment_fixture_root"
cp "$verifier" "$comment_fixture_root/tools/verify-g003-independent-builds.sh"
chmod +x "$comment_fixture_root/tools/verify-g003-independent-builds.sh"
cat >> "$comment_fixture_root/realm/realm-library/build.gradle" <<'COMMENT_FIXTURE'

// Kotlin migration documentation may mention kotlin-android.
/* This block-comment fixture also mentions kotlin-android. */
COMMENT_FIXTURE
"$comment_fixture_root/tools/verify-g003-independent-builds.sh" > "$temp_dir/comment-fixture.log"
grep -Fqx 'G003 static independent-build verification: PASS' "$temp_dir/comment-fixture.log"

# Supported modules may use either root-project property form, but the root
# targetSdkVersion must remain pinned to the expected API level.
target_fixture_root="$temp_dir/target-fixture-root"
cp -a "$comment_fixture_root" "$target_fixture_root"
sed -i 's/rootProject\.ext\.targetSdkVersion/rootProject.targetSdkVersion/g' \
  "$target_fixture_root/realm/realm-library/build.gradle" \
  "$target_fixture_root/realm/kotlin-extensions/build.gradle"
"$target_fixture_root/tools/verify-g003-independent-builds.sh" > "$temp_dir/target-fixture.log"
grep -Fqx 'G003 static independent-build verification: PASS' "$temp_dir/target-fixture.log"

sed -i 's/project\.ext\.targetSdkVersion = 37/project.ext.targetSdkVersion = 36/' \
  "$target_fixture_root/realm/build.gradle"
if "$target_fixture_root/tools/verify-g003-independent-builds.sh" \
    > "$temp_dir/wrong-root-target-fixture.log" 2>&1; then
  printf 'wrong root targetSdkVersion was accepted\n' >&2
  exit 1
fi
grep -Fqx 'F-G003-001: expected targetSdk 37 in realm/build.gradle' \
  "$temp_dir/wrong-root-target-fixture.log"

sed -i '/project\.ext\.targetSdkVersion[[:space:]]*=/d' \
  "$target_fixture_root/realm/build.gradle"
if "$target_fixture_root/tools/verify-g003-independent-builds.sh" \
    > "$temp_dir/missing-root-target-fixture.log" 2>&1; then
  printf 'missing root targetSdkVersion was accepted\n' >&2
  exit 1
fi
grep -Fqx 'F-G003-001: expected targetSdk 37 in realm/build.gradle' \
  "$temp_dir/missing-root-target-fixture.log"

printf "\napply plugin: 'kotlin-android'\n" >> "$comment_fixture_root/realm/realm-library/build.gradle"
if "$comment_fixture_root/tools/verify-g003-independent-builds.sh" \
    > "$temp_dir/real-plugin-fixture.log" 2>&1; then
  printf 'real kotlin-android plugin application was accepted\n' >&2
  exit 1
fi
grep -Fqx 'F-G003-001: Android modules must use AGP built-in Kotlin, not kotlin-android' \
  "$temp_dir/real-plugin-fixture.log"

# Exercise the full --run control flow with local fake wrappers. This crosses
# every run_gradle return without invoking Gradle or using the network, and
# protects against function-local cleanup traps leaking into later calls.
matrix_root="$temp_dir/matrix-root"
matrix_evidence="$temp_dir/matrix-evidence"
mkdir -p "$matrix_root"
git -C "$root" archive --format=tar HEAD | tar -xf - -C "$matrix_root"
cp "$verifier" "$matrix_root/tools/verify-g003-independent-builds.sh"
chmod +x "$matrix_root/tools/verify-g003-independent-builds.sh"

for wrapper in \
  gradlew \
  realm-annotations/gradlew \
  realm-transformer/gradlew \
  library-build-transformer/gradlew \
  realm/gradlew \
  gradle-plugin/gradlew; do
  cat > "$matrix_root/$wrapper" <<'GRADLEW'
#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${G003_TEST_COMMAND_TRACE:-}" ]]; then
  printf '%s\n' "$*" >> "$G003_TEST_COMMAND_TRACE"
fi
printf '> Task :synthetic:%s\n' "${1:-help}"
printf 'BUILD SUCCESSFUL\n'
GRADLEW
  chmod +x "$matrix_root/$wrapper"
done

declare -A poms=(
  [realm-annotations/build/publications/realm/pom-default.xml]=realm-annotations
  [realm-transformer/build/publications/realm/pom-default.xml]=realm-transformer
  [realm/realm-annotations-processor/build/publications/realm/pom-default.xml]=realm-annotations-processor
  [realm/realm-library/build/publications/basePublication/pom-default.xml]=realm-android-library
  [realm/kotlin-extensions/build/publications/realm/pom-default.xml]=realm-android-kotlin-extensions
  [gradle-plugin/build/publications/realm/pom-default.xml]=realm-gradle-plugin
)
for pom in "${!poms[@]}"; do
  mkdir -p "$(dirname "$matrix_root/$pom")"
  printf '<project><artifactId>%s</artifactId></project>\n' "${poms[$pom]}" > "$matrix_root/$pom"
done

G003_TEST_COMMAND_TRACE="$temp_dir/matrix-commands.log" \
  "$matrix_root/tools/verify-g003-independent-builds.sh" \
  --run --evidence-dir "$matrix_evidence" > "$temp_dir/matrix.log"
grep -Fqx "G003 independent-build matrix: PASS (evidence: $matrix_evidence)" "$temp_dir/matrix.log"
[[ "$(find "$matrix_evidence" -maxdepth 1 -name '*.log' -type f | wc -l)" -eq 12 ]]
grep -Fq ':realm-library:generatePomFileForBasePublication :kotlin-extensions:generatePomFileForRealmPublication' "$temp_dir/matrix-commands.log"
if grep -Fq ':realm-library:generatePomFileForRealmPublication' "$temp_dir/matrix-commands.log"; then
  printf 'stale realm-library RealmPublication task was requested\n' >&2
  exit 1
fi
if grep -Fq 'build/publications/realmPublication/pom-default.xml' "$verifier"; then
  printf 'stale realmPublication POM container is allowlisted\n' >&2
  exit 1
fi

printf 'G003 independent-build verifier regression tests: PASS\n'
