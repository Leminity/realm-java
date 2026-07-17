#!/usr/bin/env bash
# Runs AC-08 only against the immutable local G008 staging repository and the locked ps16k AVD.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LEADER_ROOT=/mnt/d/workspace/jiran/realm
PROJECT="$ROOT/compatibility-fixtures/ac08-api37-ps16k-runtime"
OFFICIAL_PROJECT="$PROJECT/official-project"
SDK=/home/leminity/Android/Sdk
ADB="$SDK/platform-tools/adb"
AAPT2="$SDK/build-tools/36.0.0/aapt2"
SERIAL=emulator-5654
REPOSITORY=/mnt/d/workspace/jiran/realm/build/g008-root-final-stage-run1
OFFICIAL_GRADLE="${AC08_OFFICIAL_GRADLE:-}"
OFFICIAL_PACKAGE=io.realm.ac08.official
FORK_PACKAGE=io.realm.ac08.fork
EVIDENCE_ROOT="${AC08_EVIDENCE_DIR:-$ROOT/evidence/ac08-api37-ps16k}"
RUN_ID="${AC08_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
EVIDENCE="$EVIDENCE_ROOT/$RUN_ID"
WORK="$(mktemp -d)"

cleanup() {
  rm -rf "$WORK"
}
trap cleanup EXIT

fail() {
  echo "AC08 FAIL: $*" >&2
  exit 1
}

run() {
  local name="$1"
  shift
  {
    printf '===== %s %s =====\n' "$name" "$(date --iso-8601=seconds)"
    printf '+ '
    printf '%q ' "$@"
    printf '\n'
    set +e
    "$@"
    local status=$?
    set -e
    printf '[exit=%s]\n' "$status"
    exit "$status"
  } 2>&1 | tee "$EVIDENCE/${name}.log"
}

require_instrumentation_pass() {
  local name="$1"
  local log="$EVIDENCE/${name}.log"
  # `adb shell am instrument` itself can exit 0 when the test process reports a failure.
  # Android's successful instrumentation completion code is -1; reject every other result.
  grep -Fqx 'INSTRUMENTATION_CODE: -1' "$log" || fail "$name did not report a successful instrumentation completion"
  if grep -Eq 'FAILURES!!!|Process crashed before executing|INSTRUMENTATION_STATUS_CODE: -2' "$log"; then
    fail "$name reported an instrumentation failure"
  fi
}

install_fork_inputs() {
  "$ADB" -s "$SERIAL" shell \
    "run-as $FORK_PACKAGE sh -c 'mkdir -p files/ac08 && cat /data/local/tmp/ac08-official-schema-n.realm > files/ac08/official-schema-n.realm && cat /data/local/tmp/ac08-official-encrypted.realm > files/ac08/official-encrypted.realm'"
}

capture_fork_file() {
  local remote_name="$1"
  local destination="$2"
  "$ADB" -s "$SERIAL" exec-out run-as "$FORK_PACKAGE" cat "files/ac08/$remote_name" > "$destination"
}

wait_for_fork_file() {
  local remote_name="$1"
  local destination="$2"
  local attempt
  for attempt in $(seq 1 120); do
    if capture_fork_file "$remote_name" "$destination" 2>/dev/null && grep -Eq '^pid=[1-9][0-9]*$' "$destination"; then
      cat "$destination"
      return 0
    fi
    sleep 0.25
  done
  return 1
}

device_identity() {
  local sdk page avd linker compatibility
  sdk="$("$ADB" -s "$SERIAL" shell getprop ro.build.version.sdk | tr -d '\r')"
  page="$("$ADB" -s "$SERIAL" shell getconf PAGE_SIZE | tr -d '\r')"
  avd="$("$ADB" -s "$SERIAL" shell getprop ro.boot.qemu.avd_name | tr -d '\r')"
  linker="$("$ADB" -s "$SERIAL" shell getprop bionic.linker.16kb.app_compat.enabled | tr -d '\r')"
  compatibility="$("$ADB" -s "$SERIAL" shell getprop pm.16kb.app_compat.disabled | tr -d '\r')"
  [[ "$sdk" == 37 && "$page" == 16384 && "$avd" == realm-api37-ps16k-kvm && "$linker" == fatal && "$compatibility" == true ]]
  printf 'SDK=%s PAGE_SIZE=%s AVD=%s linker_compat=%s package_compat_disabled=%s\n' "$sdk" "$page" "$avd" "$linker" "$compatibility"
}

mkdir -p "$EVIDENCE"
printf 'run_id=%s\nrepository=file://%s\nserial=%s\n' "$RUN_ID" "$REPOSITORY" "$SERIAL" \
  | tee "$EVIDENCE/run-metadata.txt"
[[ -x "$ADB" ]] || fail "expected adb at $ADB"
[[ -x "$AAPT2" ]] || fail "expected aapt2 at $AAPT2"
[[ -d "$REPOSITORY/io/github/leminity/realm" ]] || fail "missing G008 local staging repository: $REPOSITORY"
if [[ -z "$OFFICIAL_GRADLE" ]]; then
  OFFICIAL_GRADLE="$(find "$HOME/.gradle/wrapper/dists/gradle-7.5-all" -type f -path '*/bin/gradle' -print -quit 2>/dev/null || true)"
fi
[[ -x "$OFFICIAL_GRADLE" ]] || fail 'missing cached Gradle 7.5 required by the immutable official 10.19.0 plugin'

# Build without touching the device. --offline forbids JitPack/Central fallback; settings.gradle
# routes the fork group only to the absolute local Maven-layout repository.
run official-build-offline \
  "$OFFICIAL_GRADLE" -p "$OFFICIAL_PROJECT" --offline --no-daemon --console=plain \
  -Pandroid.aapt2FromMavenOverride="$AAPT2" \
  :official-app:assembleDebug :official-app:assembleDebugAndroidTest
run fork-build-offline env G008_STAGING_REPOSITORY="file://$REPOSITORY" \
  "$ROOT/gradlew" -p "$PROJECT" --offline --no-daemon --console=plain \
  :fork-app:assembleDebug :fork-app:assembleDebugAndroidTest
run fork-resolution env G008_STAGING_REPOSITORY="file://$REPOSITORY" \
  "$ROOT/gradlew" -p "$PROJECT" --offline --no-daemon --console=plain \
  :fork-app:dependencies --configuration debugRuntimeClasspath
grep -Fq 'io.github.leminity.realm:realm-android-library:10.19.0-agp9.1' "$EVIDENCE/fork-resolution.log" ||
  fail 'fork runtime did not resolve from G008 staging'
run g008-artifact-manifest find "$REPOSITORY/io/github/leminity/realm" -type f -maxdepth 6 -print
if grep -Rqi 'jitpack\.io' "$PROJECT"/*.gradle "$PROJECT"/*/build.gradle "$PROJECT"/*/settings.gradle; then
  fail 'AC-08 harness must not configure JitPack'
fi

# Both advertised transports refer to the same AVD. Device operations are atomic with AC-07.
exec 9>/tmp/realm-g009-device.lock
flock -x 9
trap 'flock -u 9; cleanup' EXIT

run device-identity device_identity

OFFICIAL_APK="$PROJECT/official-app/build/outputs/apk/debug/official-app-debug.apk"
OFFICIAL_TEST_APK="$PROJECT/official-app/build/outputs/apk/androidTest/debug/official-app-debug-androidTest.apk"
FORK_APK="$PROJECT/fork-app/build/outputs/apk/debug/fork-app-debug.apk"
FORK_TEST_APK="$PROJECT/fork-app/build/outputs/apk/androidTest/debug/fork-app-debug-androidTest.apk"
for apk in "$OFFICIAL_APK" "$OFFICIAL_TEST_APK" "$FORK_APK" "$FORK_TEST_APK"; do
  [[ -f "$apk" ]] || fail "missing assembled APK $apk"
done

run install-official "$ADB" -s "$SERIAL" install -r -t "$OFFICIAL_APK"
run install-official-test "$ADB" -s "$SERIAL" install -r -t "$OFFICIAL_TEST_APK"
run clear-official-data "$ADB" -s "$SERIAL" shell pm clear "$OFFICIAL_PACKAGE"
run official-schema-n "$ADB" -s "$SERIAL" shell am instrument -w -r \
  -e class io.realm.ac08.official.OfficialSchemaFixtureTest \
  "$OFFICIAL_PACKAGE.test/androidx.test.runner.AndroidJUnitRunner"
require_instrumentation_pass official-schema-n

OFFICIAL_SCHEMA="$WORK/official-schema-n.realm"
OFFICIAL_CATEGORY="$WORK/official-no-migration-category.txt"
OFFICIAL_THREAD_CATEGORIES="$WORK/official-thread-categories.txt"
# exec-out is binary-safe; keep the Realm payload out of the textual evidence stream.
"$ADB" -s "$SERIAL" exec-out run-as "$OFFICIAL_PACKAGE" cat files/ac08/official-schema-n.realm > "$OFFICIAL_SCHEMA"
"$ADB" -s "$SERIAL" exec-out run-as "$OFFICIAL_PACKAGE" cat files/ac08/no-migration-category.txt > "$OFFICIAL_CATEGORY"
"$ADB" -s "$SERIAL" exec-out run-as "$OFFICIAL_PACKAGE" cat files/ac08/thread-categories.txt > "$OFFICIAL_THREAD_CATEGORIES"
SCHEMA_HASH="$(sha256sum "$OFFICIAL_SCHEMA" | awk '{print $1}')"
CATEGORY="$(tr -d '\r\n' < "$OFFICIAL_CATEGORY")"
OFFICIAL_REALM_THREAD_CATEGORY="$(awk -F= '$1 == "realm" { print $2 }' "$OFFICIAL_THREAD_CATEGORIES")"
OFFICIAL_OBJECT_THREAD_CATEGORY="$(awk -F= '$1 == "managed_object" { print $2 }' "$OFFICIAL_THREAD_CATEGORIES")"
OFFICIAL_RESULTS_THREAD_CATEGORY="$(awk -F= '$1 == "results" { print $2 }' "$OFFICIAL_THREAD_CATEGORIES")"
[[ "$CATEGORY" == 'io.realm.exceptions.RealmMigrationNeededException' ]] || fail "unexpected official no-migration category: $CATEGORY"
for expected in "$OFFICIAL_REALM_THREAD_CATEGORY" "$OFFICIAL_OBJECT_THREAD_CATEGORY" "$OFFICIAL_RESULTS_THREAD_CATEGORY"; do
  [[ "$expected" == 'java.lang.IllegalStateException' ]] || fail "unexpected official thread category: $expected"
done
printf 'schema_sha256=%s\nofficial_no_migration_category=%s\nofficial_realm_thread_category=%s\nofficial_managed_object_thread_category=%s\nofficial_results_thread_category=%s\n' \
  "$SCHEMA_HASH" "$CATEGORY" "$OFFICIAL_REALM_THREAD_CATEGORY" "$OFFICIAL_OBJECT_THREAD_CATEGORY" "$OFFICIAL_RESULTS_THREAD_CATEGORY" \
  | tee "$EVIDENCE/export-official-schema.log"

IMMUTABLE_ENCRYPTED="$LEADER_ROOT/compatibility-fixtures/official-10.19.0-generator/generated/official-10.19.0-oracle/official-10.19.0-encrypted.realm"
[[ -f "$IMMUTABLE_ENCRYPTED" ]] || fail "missing immutable encrypted official input"
ENCRYPTED_HASH="$(sha256sum "$IMMUTABLE_ENCRYPTED" | awk '{print $1}')"
printf 'encrypted_sha256=%s\n' "$ENCRYPTED_HASH" | tee "$EVIDENCE/immutable-input-manifest.txt"

run install-fork "$ADB" -s "$SERIAL" install -r -t "$FORK_APK"
run install-fork-test "$ADB" -s "$SERIAL" install -r -t "$FORK_TEST_APK"
run clear-fork-data "$ADB" -s "$SERIAL" shell pm clear "$FORK_PACKAGE"
run push-schema "$ADB" -s "$SERIAL" push "$OFFICIAL_SCHEMA" /data/local/tmp/ac08-official-schema-n.realm
run push-encrypted "$ADB" -s "$SERIAL" push "$IMMUTABLE_ENCRYPTED" /data/local/tmp/ac08-official-encrypted.realm
run install-inputs install_fork_inputs

# Phase A deliberately remains alive after committing sentinels. It records its own PID
# before the host force-stops the target package, proving that the restart is not just an
# Activity re-launch. Phase B is a fresh instrumentation process that reopens both files.
PHASE_A_FILE="$WORK/phase-a.txt"
PHASE_B_FILE="$WORK/phase-b.txt"
run phase-a-instrumentation "$ADB" -s "$SERIAL" shell am instrument -r \
  -e class io.realm.ac08.fork.RestartPhaseTest#phaseACommitsSentinelsAndWaitsForForceStop \
  "$FORK_PACKAGE.test/androidx.test.runner.AndroidJUnitRunner"
run phase-a-evidence wait_for_fork_file restart-phase-a.txt "$PHASE_A_FILE"
PID_A="$(awk -F= '$1 == "pid" { print $2 }' "$PHASE_A_FILE")"
PID_A_LIVE="$("$ADB" -s "$SERIAL" shell pidof "$FORK_PACKAGE" | tr -d '\r')"
[[ "$PID_A_LIVE" == "$PID_A" ]] || fail "phase A instrumentation PID mismatch (evidence=$PID_A live=$PID_A_LIVE)"
printf 'pid_a=%s\npid_a_matches_live=PASS\n' "$PID_A" | tee "$EVIDENCE/force-stop-pids.txt"
run phase-a-force-stop "$ADB" -s "$SERIAL" shell am force-stop "$FORK_PACKAGE"
for _ in $(seq 1 30); do
  if ! "$ADB" -s "$SERIAL" shell pidof "$FORK_PACKAGE" >/dev/null 2>&1; then break; fi
  sleep 0.2
done
if "$ADB" -s "$SERIAL" shell pidof "$FORK_PACKAGE" >/dev/null 2>&1; then
  fail "force-stop left phase-A PID alive: $PID_A"
fi
printf 'pid_a_absent=PASS\n' | tee -a "$EVIDENCE/force-stop-pids.txt"
run phase-b-instrumentation "$ADB" -s "$SERIAL" shell am instrument -w -r \
  -e class io.realm.ac08.fork.RestartPhaseTest#phaseBReopensAndVerifiesSentinels \
  "$FORK_PACKAGE.test/androidx.test.runner.AndroidJUnitRunner"
require_instrumentation_pass phase-b-instrumentation
run phase-b-evidence capture_fork_file restart-phase-b.txt "$PHASE_B_FILE"
# Persist the instrumentation-generated phase-B PID and both reopened sentinels beside the
# command record without making phase-A polling print transient missing-file errors.
cat "$PHASE_B_FILE" | tee -a "$EVIDENCE/phase-b-evidence.log"
PID_B="$(awk -F= '$1 == "pid" { print $2 }' "$PHASE_B_FILE")"
[[ "$PID_B" =~ ^[1-9][0-9]*$ && "$PID_B" != "$PID_A" ]] || fail "phase B PID must differ from phase A (A=$PID_A B=$PID_B)"
printf 'pid_b=%s\npid_b_differs=PASS\n' "$PID_B" | tee -a "$EVIDENCE/force-stop-pids.txt"

run fork-runtime "$ADB" -s "$SERIAL" shell am instrument -w -r \
  -e class io.realm.ac08.fork.ForkRuntimeTest \
  -e schema_sha256 "$SCHEMA_HASH" \
  -e encrypted_sha256 "$ENCRYPTED_HASH" \
  -e official_no_migration_category "$CATEGORY" \
  -e official_realm_thread_category "$OFFICIAL_REALM_THREAD_CATEGORY" \
  -e official_managed_object_thread_category "$OFFICIAL_OBJECT_THREAD_CATEGORY" \
  -e official_results_thread_category "$OFFICIAL_RESULTS_THREAD_CATEGORY" \
  "$FORK_PACKAGE.test/androidx.test.runner.AndroidJUnitRunner"
require_instrumentation_pass fork-runtime
run fork-package "$ADB" -s "$SERIAL" shell dumpsys package "$FORK_PACKAGE"
if grep -Fq 'android.permission.INTERNET' "$EVIDENCE/fork-package.log"; then
  fail 'fork package declares INTERNET; AC-08 requires zero network'
fi
run fork-logcat "$ADB" -s "$SERIAL" logcat -d -v threadtime

(
  cd "$EVIDENCE"
  find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\0' | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS > checksum-verify.log
)
printf 'AC08=PASS\n' | tee "$EVIDENCE/result.txt"
