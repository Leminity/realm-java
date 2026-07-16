#!/usr/bin/env bash
# Verifies the public AGP 9 API boundary used by realm-transformer (G004).
set -euo pipefail

readonly EXPECTED_AGP='9.1.1'
readonly EXPECTED_MIN_SDK='21'
readonly EXPECTED_TARGET_SDK='37'

root="${ROOT_OVERRIDE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
mode='static'

fail() {
  printf 'G004 transformer public-API verification: %s\n' "$*" >&2
  exit 1
}

require_text() {
  local text=$1 file=$2
  grep -Fq -- "$text" "$file" || fail "expected '$text' in $file"
}

reject_text() {
  local text=$1 file=$2
  if grep -Fq -- "$text" "$file"; then
    fail "forbidden '$text' remains in $file"
  fi
}

verify_static() {
  local project_ext="$root/realm-transformer/src/main/kotlin/io/realm/transformer/ext/ProjectExt.kt"
  local transformer="$root/realm-transformer/src/main/kotlin/io/realm/transformer/RealmTransformer.kt"

  require_text 'import com.android.build.api.dsl.ApplicationExtension' "$project_ext"
  require_text 'import com.android.build.api.dsl.LibraryExtension' "$project_ext"
  require_text 'import com.android.build.api.variant.AndroidComponentsExtension' "$project_ext"
  require_text 'ApplicationExtension::class.java' "$project_ext"
  require_text 'LibraryExtension::class.java' "$project_ext"
  require_text '?.targetSdk' "$project_ext"
  require_text '?.minSdk' "$project_ext"
  require_text 'AndroidComponentsExtension::class.java).pluginVersion' "$project_ext"
  reject_text 'com.android.build.gradle.BaseExtension' "$project_ext"
  reject_text 'getAndroidExtension' "$project_ext"
  reject_text 'getBootClasspath' "$project_ext"

  require_text 'import com.android.build.api.dsl.SdkComponents' "$transformer"
  require_text 'project.extensions.getByType(SdkComponents::class.java)' "$transformer"
  require_text 'referencedInputs.setFrom(variant.compileClasspath)' "$transformer"
  require_text 'bootClasspath.setFrom(sdkComponents.bootClasspath)' "$transformer"
  require_text 'ScopedArtifacts.Scope.PROJECT' "$transformer"
  require_text 'FileSystems.newFileSystem(output.get().asFile.toPath(), emptyMap<String, Any>())' "$transformer"
  reject_text 'com.android.build.gradle.internal' "$transformer"
  reject_text 'AndroidArtifacts' "$transformer"

  # The callback is registered for all production variants; fixture runs below
  # validate the app/library × Java/Kotlin × debug/release matrix and cache reuse.
  require_text 'androidComponents.onVariants { variant ->' "$transformer"
  printf 'G004 transformer public-API static verification: PASS\n'
}

write_fixture() {
  local fixture=$1 kind=$2 language=$3
  mkdir -p "$fixture/app/src/main/$language/fixture"
  cat > "$fixture/settings.gradle" <<'EOF'
pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { google(); mavenCentral() }
}
rootProject.name = 'g004-transformer-fixture'
include ':app'
EOF
  cat > "$fixture/build.gradle" <<EOF
buildscript {
    repositories { google(); mavenCentral() }
    dependencies {
        classpath 'com.android.tools.build:gradle:$EXPECTED_AGP'
        classpath files('$transformer_jar')
    }
}
EOF
  cat > "$fixture/app/build.gradle" <<EOF
apply plugin: 'com.android.$kind'

android {
    namespace 'fixture.$kind.$language'
    compileSdk $EXPECTED_TARGET_SDK
    defaultConfig {
        minSdk $EXPECTED_MIN_SDK
    }
}

io.realm.transformer.RealmTransformerKt.registerRealmTransformerTask(project)
EOF
  if [[ "$kind" == application ]]; then
    sed -i "/minSdk $EXPECTED_MIN_SDK/a\\        applicationId 'fixture.$kind.$language'\\n        targetSdk $EXPECTED_TARGET_SDK\\n        versionCode 1\\n        versionName '1.0'" "$fixture/app/build.gradle"
  fi
  cat > "$fixture/app/src/main/AndroidManifest.xml" <<EOF
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="fixture.$kind.$language" />
EOF
  if [[ "$language" == java ]]; then
    cat > "$fixture/app/src/main/java/fixture/Fixture.java" <<'EOF'
package fixture;
public final class Fixture { private int value; }
EOF
  else
    cat > "$fixture/app/src/main/kotlin/fixture/Fixture.kt" <<'EOF'
package fixture
class Fixture(private var value: Int)
EOF
  fi
}

run_fixture() {
  local kind=$1 language=$2 fixture log first second
  fixture="$(mktemp -d)"
  write_fixture "$fixture" "$kind" "$language"

  first="$fixture/first.log"
  second="$fixture/second.log"
  (
    cd "$fixture"
    "$root/realm-transformer/gradlew" --no-daemon --console=plain \
      :app:tasks --all --configuration-cache
  ) >"$first" 2>&1 || { cat "$first" >&2; fail "$kind/$language first configuration failed"; }
  grep -Fq 'debugRealmAccessorsTransformer' "$first" || fail "$kind/$language missing debug transformer task"
  grep -Fq 'releaseRealmAccessorsTransformer' "$first" || fail "$kind/$language missing release transformer task"

  (
    cd "$fixture"
    "$root/realm-transformer/gradlew" --no-daemon --console=plain \
      :app:tasks --all --configuration-cache
  ) >"$second" 2>&1 || { cat "$second" >&2; fail "$kind/$language cache reuse failed"; }
  grep -Fq 'Reusing configuration cache.' "$second" ||
    fail "$kind/$language did not reuse its configuration cache"
  printf 'G004 fixture %s/%s: PASS\n' "$kind" "$language"
  rm -rf "$fixture"
}

run_matrix() {
  (
    cd "$root/realm-transformer"
    ./gradlew --no-daemon --console=plain jar
  )
  transformer_jar="$(find "$root/realm-transformer/build/libs" -maxdepth 1 -name 'realm-transformer-*.jar' | head -1)"
  [[ -n "$transformer_jar" ]] || fail 'realm-transformer jar was not produced'
  for kind in application library; do
    for language in java kotlin; do
      run_fixture "$kind" "$language"
    done
  done
}

case "${1:-}" in
  '') ;;
  --run) mode='run' ;;
  *) fail 'usage: tools/verify-g004-transformer-public-api.sh [--run]' ;;
esac

verify_static
if [[ "$mode" == run ]]; then
  run_matrix
fi
