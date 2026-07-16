#!/usr/bin/env bash
# Verifies the G003 supported independent-build chain after F-G003-001.
#
# This is intentionally a build-logic black-box verifier.  It does not change
# Gradle configuration, publish anything, or configure examples/benchmarks.
set -euo pipefail

readonly FAILURE_ID='F-G003-001'
readonly EXPECTED_AGP='9.1.1'
readonly EXPECTED_GRADLE='9.6.1'
readonly EXPECTED_KOTLIN='2.2.10'
readonly EXPECTED_NDK='29.0.14206865'
readonly EXPECTED_JAVA_MAJOR='17'
readonly EXPECTED_GRADLE_URL='https\://services.gradle.org/distributions/gradle-9.6.1-bin.zip'
readonly EXPECTED_GRADLE_SHA256='9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14'

readonly -a WRAPPERS=(
  gradle/wrapper/gradle-wrapper.properties
  realm-annotations/gradle/wrapper/gradle-wrapper.properties
  realm-transformer/gradle/wrapper/gradle-wrapper.properties
  library-build-transformer/gradle/wrapper/gradle-wrapper.properties
  realm/gradle/wrapper/gradle-wrapper.properties
  gradle-plugin/gradle/wrapper/gradle-wrapper.properties
)
readonly -a SUPPORTED_BUILD_SCRIPTS=(
  build.gradle
  realm-annotations/build.gradle
  realm-transformer/build.gradle
  library-build-transformer/build.gradle
  realm/build.gradle
  realm/realm-annotations-processor/build.gradle
  realm/realm-library/build.gradle
  realm/kotlin-extensions/build.gradle
  gradle-plugin/build.gradle
  mavencentral-properties.gradle
  mavencentral-publications.gradle
  mavencentral-publish.gradle
)
readonly -a FORBIDDEN_LOG_PATTERN=(
  'static\.realm\.io'
  's3://'
  's3cmd'
  'oss\.sonatype\.org'
  'publishToSonatype'
  '(^|[^[:alnum:]])examples?([^[:alnum:]]|$)'
  'library-benchmarks'
  'object[Ss]erver'
  'syncIntegrationTest'
  'androidTestObjectServer'
)

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode='static'
release_task=''
evidence_dir=''
check_log=''

usage() {
  cat <<'USAGE'
usage: tools/verify-g003-independent-builds.sh [options]

Static checks (the default) validate exact G003 pins and reject legacy
repositories/opt-outs in the supported build scripts.

Options:
  --run                    Also run the ordered independent-build matrix.
  --release-task TASK      Dry-run TASK in the root and assert its graph is
                           free of unsupported release work.
  --evidence-dir PATH      Directory for --run command logs.
  --check-log PATH         Check an existing Gradle log for forbidden graph or
                           network activity (used by the regression test).
  -h, --help               Show this help.
USAGE
}

fail() {
  printf '%s: %s\n' "$FAILURE_ID" "$*" >&2
  exit 1
}

require_line() {
  local expected=$1 file=$2
  grep -Fqx "$expected" "$file" || fail "expected '$expected' in $file"
}

check_log_for_forbidden_activity() {
  local log=$1 pattern
  [[ -f "$log" ]] || fail "missing Gradle log: $log"
  for pattern in "${FORBIDDEN_LOG_PATTERN[@]}"; do
    if grep -Ein -- "$pattern" "$log" >/dev/null; then
      fail "unsupported graph or network activity ($pattern) in $log"
    fi
  done
}

verify_java() {
  local version
  version="$(java -version 2>&1 | head -n 1)"
  [[ "$version" =~ \"${EXPECTED_JAVA_MAJOR}([.\"]|$) ]] || \
    fail "expected JDK $EXPECTED_JAVA_MAJOR, got: $version"
}

verify_static() {
  local script wrapper
  cd "$root"

  require_line "GRADLE_BUILD_TOOLS=$EXPECTED_AGP" dependencies.list
  require_line "gradle=$EXPECTED_GRADLE" dependencies.list
  require_line "KOTLIN=$EXPECTED_KOTLIN" dependencies.list
  require_line "ndkVersion=$EXPECTED_NDK" dependencies.list

  for wrapper in "${WRAPPERS[@]}"; do
    require_line "distributionUrl=$EXPECTED_GRADLE_URL" "$wrapper"
    require_line "distributionSha256Sum=$EXPECTED_GRADLE_SHA256" "$wrapper"
  done

  for script in "${SUPPORTED_BUILD_SCRIPTS[@]}"; do
    [[ -f "$script" ]] || fail "missing supported build script: $script"
    if grep -En -- '\bjcenter[[:space:]]*\(' "$script" >/dev/null; then
      fail "legacy jcenter() remains in $script"
    fi
  done

  if grep -REn --include='*.gradle' --include='gradle.properties' \
      'android\.(newDsl|builtInKotlin)[[:space:]]*=[[:space:]]*false' \
      build.gradle gradle.properties realm realm-annotations realm-transformer \
      library-build-transformer gradle-plugin >/dev/null; then
    fail 'legacy AGP opt-out is forbidden'
  fi

  if grep -REn --include='*.gradle' -- 'kotlin-android' realm >/dev/null; then
    fail 'Android modules must use AGP built-in Kotlin, not kotlin-android'
  fi

  if grep -Fq '/.m2/repository/io/realm' build.gradle; then
    fail 'root clean task still targets the legacy io.realm Maven path'
  fi

  verify_java
  printf 'G003 static independent-build verification: PASS\n'
}

run_gradle() {
  local label=$1 directory=$2
  shift 2
  local log="$evidence_dir/$label.log"
  printf 'G003 %s: %s\n' "$label" "$*"
  (
    cd "$root/$directory"
    ./gradlew --no-daemon --console=plain --stacktrace \
      "-Dmaven.repo.local=$staged_maven_repo" "$@"
  ) >"$log" 2>&1 || {
    tail -n 160 "$log" >&2
    fail "$label failed; full log: $log"
  }
  check_log_for_forbidden_activity "$log"
}

run_matrix() {
  local temp_dir
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "$temp_dir"' EXIT
  evidence_dir="${evidence_dir:-$root/build/g003-independent-builds}"
  staged_maven_repo="$temp_dir/maven-repository"
  mkdir -p "$evidence_dir" "$staged_maven_repo"
  export GRADLE_USER_HOME="$temp_dir/gradle-user-home"

  # The ordering is the G003 release-critical contract.  Only the first three
  # prerequisite builds publish to the temporary local repository; the Realm
  # build never uses broad publish/assemble tasks because they historically
  # include unsupported ObjectServer/Sync work.
  run_gradle annotations-help realm-annotations help
  run_gradle annotations-test-metadata realm-annotations test generatePomFileForRealmPublication publishToMavenLocal
  run_gradle transformer-help realm-transformer help
  run_gradle transformer-test-metadata realm-transformer test generatePomFileForRealmPublication publishToMavenLocal
  run_gradle build-transformer-help library-build-transformer help
  run_gradle build-transformer-test-metadata library-build-transformer test generatePomFileForRealmPublication publishToMavenLocal
  run_gradle realm-help realm help
  run_gradle realm-processor-metadata realm :realm-annotations-processor:test :realm-annotations-processor:generatePomFileForRealmPublication
  run_gradle realm-base-metadata realm :realm-library:generatePomFileForRealmPublication :kotlin-extensions:generatePomFileForRealmPublication
  run_gradle gradle-plugin-help gradle-plugin help
  run_gradle gradle-plugin-test-metadata gradle-plugin test generatePomFileForRealmPublication

  if [[ -n "$release_task" ]]; then
    run_gradle "root-${release_task//:/_}-dry-run" . --dry-run "$release_task"
  fi

  printf 'G003 independent-build matrix: PASS (evidence: %s)\n' "$evidence_dir"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run) mode='run'; shift ;;
    --release-task) release_task=${2:?missing task name}; shift 2 ;;
    --evidence-dir) evidence_dir=${2:?missing evidence directory}; shift 2 ;;
    --check-log) check_log=${2:?missing log path}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; fail "unknown option: $1" ;;
  esac
done

if [[ -n "$check_log" ]]; then
  check_log_for_forbidden_activity "$check_log"
  printf 'G003 log assertion: PASS\n'
  exit 0
fi

verify_static
if [[ "$mode" == 'run' ]]; then
  run_matrix
fi
