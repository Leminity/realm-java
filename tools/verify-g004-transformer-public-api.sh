#!/usr/bin/env bash
# Verifies the public AGP 9 API boundary used by realm-transformer (G004).
set -euo pipefail

readonly EXPECTED_AGP='9.1.1'
readonly EXPECTED_MIN_SDK='21'
readonly EXPECTED_TARGET_SDK='37'
readonly FORK_GROUP='io.github.leminity.realm'

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

  require_text 'referencedInputs.setFrom(variant.compileClasspath)' "$transformer"
  require_text 'bootClasspath.setFrom(androidComponents.sdkComponents.bootClasspath)' "$transformer"
  require_text 'ScopedArtifacts.Scope.PROJECT' "$transformer"
  require_text 'FileSystems.newFileSystem(output.get().asFile.toPath(), emptyMap<String, Any>())' "$transformer"
  reject_text 'com.android.build.gradle.internal' "$transformer"
  reject_text 'AndroidArtifacts' "$transformer"

  # The callback is registered for all production variants; fixture runs below
  # execute each app/library × Java/Kotlin × debug/release transform and cache reuse.
  require_text 'androidComponents.onVariants { variant ->' "$transformer"
  printf 'G004 transformer public-API static verification: PASS\n'
}

write_fixture() {
  local fixture=$1 kind=$2 language=$3
  mkdir -p "$fixture/app/src/main/$language/fixture"
  printf 'sdk.dir=%s\n' "$sdk_dir" > "$fixture/local.properties"
  cat > "$fixture/settings.gradle" <<EOF
pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        maven { url = uri('$staged_maven_repo') }
        google()
        mavenCentral()
    }
}
rootProject.name = 'g004-transformer-fixture'
include ':app'
EOF
  cat > "$fixture/build.gradle" <<EOF
buildscript {
    repositories {
        maven { url = uri('$staged_maven_repo') }
        google()
        mavenCentral()
    }
    dependencies {
        classpath 'com.android.tools.build:gradle:$EXPECTED_AGP'
        classpath files('$transformer_jar')
        classpath 'org.javassist:javassist:3.25.0-GA'
        classpath '$FORK_GROUP:realm-annotations:$transformer_version'
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

dependencies {
    implementation '$FORK_GROUP:realm-android-library:$transformer_version'
}

io.realm.transformer.RealmTransformerKt.registerRealmTransformerTask(project)
EOF
  if [[ "$kind" == application ]]; then
    sed -i "/minSdk $EXPECTED_MIN_SDK/a\\        applicationId 'fixture.$kind.$language'\\n        targetSdk $EXPECTED_TARGET_SDK\\n        versionCode 1\\n        versionName '1.0'" "$fixture/app/build.gradle"
  fi
  cat > "$fixture/app/src/main/AndroidManifest.xml" <<'EOF'
<manifest />
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
  fixture="$(mktemp -d "$matrix_temp_dir/fixture-$kind-$language-XXXXXX")"
  write_fixture "$fixture" "$kind" "$language"

  first="$fixture/first.log"
  second="$fixture/second.log"
  (
    cd "$fixture"
    "$root/realm-transformer/gradlew" --no-daemon --console=plain \
      --gradle-user-home "$gradle_user_home" \
      "-Dmaven.repo.local=$staged_maven_repo" \
      :app:debugRealmAccessorsTransformer :app:releaseRealmAccessorsTransformer \
      --configuration-cache
  ) >"$first" 2>&1 || { cat "$first" >&2; fail "$kind/$language first configuration failed"; }
  grep -Fq '> Task :app:debugRealmAccessorsTransformer' "$first" || fail "$kind/$language did not execute debug transformer task"
  grep -Fq '> Task :app:releaseRealmAccessorsTransformer' "$first" || fail "$kind/$language did not execute release transformer task"

  (
    cd "$fixture"
    "$root/realm-transformer/gradlew" --no-daemon --console=plain \
      --gradle-user-home "$gradle_user_home" \
      "-Dmaven.repo.local=$staged_maven_repo" \
      :app:debugRealmAccessorsTransformer :app:releaseRealmAccessorsTransformer \
      --configuration-cache
  ) >"$second" 2>&1 || { cat "$second" >&2; fail "$kind/$language cache reuse failed"; }
  grep -Fq 'Reusing configuration cache.' "$second" ||
    fail "$kind/$language did not reuse its configuration cache"
  printf 'G004 fixture %s/%s: PASS\n' "$kind" "$language"
  rm -rf "$fixture"
}

run_project_gradle() {
  local label=$1 directory=$2
  shift 2
  printf 'G004 %s: %s\n' "$label" "$*"
  (
    cd "$root/$directory"
    ./gradlew --no-daemon --console=plain --stacktrace \
      --gradle-user-home "$gradle_user_home" \
      "-Dmaven.repo.local=$staged_maven_repo" "$@"
  )
}

stage_fixture_dependencies() {
  # Stage only the build prerequisites and the supported base Realm AAR. A
  # broad Realm publication would also select unsupported ObjectServer/Sync
  # variants and is intentionally forbidden here.
  run_project_gradle annotations-local-stage realm-annotations publishToMavenLocal
  run_project_gradle transformer-local-stage realm-transformer publishToMavenLocal
  run_project_gradle build-transformer-local-stage library-build-transformer publishToMavenLocal
  run_project_gradle realm-base-local-stage realm :realm-library:publishBasePublicationToMavenLocal
}

cleanup_matrix() {
  if [[ -n "${matrix_temp_dir:-}" && -d "$matrix_temp_dir" ]]; then
    rm -rf "$matrix_temp_dir"
  fi
}

select_primary_transformer_jar() {
  local libraries_dir=$1 transformer_version=$2 primary_jar
  primary_jar="$libraries_dir/realm-transformer-$transformer_version.jar"
  [[ -f "$primary_jar" ]] || fail "primary transformer jar was not produced: $primary_jar"
  printf '%s\n' "$primary_jar"
}

run_matrix() {
  matrix_temp_dir="$(mktemp -d)"
  staged_maven_repo="$matrix_temp_dir/maven-repository"
  gradle_user_home="$matrix_temp_dir/gradle-user-home"
  mkdir -p "$staged_maven_repo" "$gradle_user_home"
  trap cleanup_matrix EXIT

  stage_fixture_dependencies
  transformer_version="$(tr -d '[:space:]' < "$root/version.txt")"
  transformer_jar="$(select_primary_transformer_jar "$root/realm-transformer/build/libs" "$transformer_version")"
  sdk_dir="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
  if [[ -z "$sdk_dir" && -d "$HOME/Android/Sdk" ]]; then
    sdk_dir="$HOME/Android/Sdk"
  fi
  [[ -d "$sdk_dir/platforms" ]] || fail 'set ANDROID_HOME or ANDROID_SDK_ROOT to an Android SDK'
  for kind in application library; do
    for language in java kotlin; do
      run_fixture "$kind" "$language"
    done
  done
  cleanup_matrix
  trap - EXIT
}

main() {
  case "${1:-}" in
    '') ;;
    --run) mode='run' ;;
    *) fail 'usage: tools/verify-g004-transformer-public-api.sh [--run]' ;;
  esac

  verify_static
  if [[ "$mode" == run ]]; then
    run_matrix
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
