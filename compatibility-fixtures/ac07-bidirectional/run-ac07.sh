#!/usr/bin/env bash
# AC-07 bidirectional official 10.19.0 <-> fork compatibility runner.
# Inputs are copied into a new, ignored run directory; the supplied oracle is never writable.
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
official_project="$repo_root/compatibility-fixtures/official-10.19.0-generator"
fork_project="$project_dir/fork-consumer"
sdk_root=${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}
adb="$sdk_root/platform-tools/adb"
aapt2=${AAPT2_OVERRIDE:-$sdk_root/build-tools/36.0.0/aapt2}

fixtures=''
fork_repository=''
fork_serial=''
official_serial=''
run_dir=''
while (($#)); do
    case "$1" in
        --official-fixtures) fixtures=${2:?missing fixture directory}; shift 2 ;;
        --fork-repository) fork_repository=${2:?missing local Maven repository}; shift 2 ;;
        --fork-serial) fork_serial=${2:?missing fork serial}; shift 2 ;;
        --official-serial) official_serial=${2:?missing official reader serial}; shift 2 ;;
        --run-dir) run_dir=${2:?missing run directory}; shift 2 ;;
        -h|--help)
            cat <<USAGE
usage: $0 --official-fixtures <immutable fixture dir> --fork-repository <verified G008 local repo> --fork-serial <API37 serial> --official-serial <official-reader serial> [--run-dir <new evidence dir>]

The fixture directory must contain the two official .realm files and fixture-manifest.json
exported by compatibility-fixtures/official-10.19.0-generator/run-official-oracle.sh.
It is copied read-only into a fresh run directory. A failed stage leaves its log there.
USAGE
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
[[ -n "$fixtures" && -d "$fixtures" ]] || { echo '--official-fixtures must name an existing immutable oracle directory' >&2; exit 2; }
[[ -n "$fork_repository" && -d "$fork_repository" ]] || { echo '--fork-repository must name an existing verified local Maven-layout directory' >&2; exit 2; }
[[ -n "$fork_serial" ]] || { echo '--fork-serial is required; the fork side must be explicit' >&2; exit 2; }
[[ -n "$official_serial" ]] || { echo '--official-serial is required; reverse-read device must be explicit' >&2; exit 2; }
[[ -x "$adb" ]] || { echo "Missing adb: $adb" >&2; exit 2; }
[[ -x "$aapt2" ]] || { echo "Missing AAPT2 override: $aapt2" >&2; exit 2; }

fixtures=$(cd "$fixtures" && pwd)
fork_repository=$(cd "$fork_repository" && pwd)
if [[ -z "$run_dir" ]]; then
    mkdir -p "$project_dir/generated"
    run_dir=$(mktemp -d "$project_dir/generated/ac07.XXXXXX")
elif [[ -e "$run_dir" ]]; then
    echo "--run-dir must not already exist, preventing evidence from separate attempts being mixed: $run_dir" >&2
    exit 2
else
    mkdir -p "$run_dir"
fi
run_dir=$(cd "$run_dir" && pwd)
mkdir -p "$run_dir/logs" "$run_dir/original" "$run_dir/fork-modified"

export ANDROID_HOME="$sdk_root"
export ANDROID_SDK_ROOT="$sdk_root"
export ANDROID_AAPT2_FROM_MAVEN_OVERRIDE="$aapt2"
key_hex=$(tr -d '\r\n' < "$official_project/fixed-test-key.hex")
[[ "$key_hex" =~ ^[0-9A-Fa-f]{128}$ ]] || { echo 'Fixture key has invalid length' >&2; exit 2; }
key_hash=$(printf '%s' "$key_hex" | xxd -r -p | sha256sum | awk '{print $1}')

log() { printf '[ac07] %s\n' "$*" | tee -a "$run_dir/runner.log"; }
run_logged() {
    local label=$1
    shift
    log "START $label: $(printf '%q ' "$@")"
    "$@" >"$run_dir/logs/$label.log" 2>&1 || {
        local status=$?
        log "FAIL $label (exit=$status); preserved $run_dir/logs/$label.log"
        exit "$status"
    }
    log "PASS $label"
}
run_instrumentation() {
    local label=$1
    shift
    log "START $label: $(printf '%q ' "$@")"
    "$@" >"$run_dir/logs/$label.log" 2>&1 || {
        local status=$?
        log "FAIL $label (adb exit=$status); preserved $run_dir/logs/$label.log"
        exit "$status"
    }
    if grep -Eq 'INSTRUMENTATION_STATUS_CODE: -2|FAILURES!!!|There was [0-9]+ failure' "$run_dir/logs/$label.log" || \
       ! grep -Eq '^OK \([0-9]+ test' "$run_dir/logs/$label.log"; then
        log "FAIL $label (instrumentation did not report an all-tests-passed result); preserved $run_dir/logs/$label.log"
        exit 1
    fi
    log "PASS $label"
}
assert_device() {
    local serial=$1 label=$2
    run_logged "$label-device-state" "$adb" -s "$serial" get-state
    grep -qx device "$run_dir/logs/$label-device-state.log" || { echo "$label device is not ready: $serial" >&2; exit 3; }
    "$adb" -s "$serial" shell getprop ro.build.version.sdk > "$run_dir/logs/$label-api-level.log"
    "$adb" -s "$serial" shell getconf PAGESIZE > "$run_dir/logs/$label-page-size.log" || true
}
copy_to_app() {
    local serial=$1 package=$2 app_dir=$3 source=$4
    local name
    name=$(basename "$source")
    "$adb" -s "$serial" exec-in run-as "$package" sh -c "mkdir -p files/$app_dir && cat > files/$app_dir/$name" < "$source"
}
copy_from_app() {
    local serial=$1 package=$2 app_dir=$3 name=$4 destination=$5
    "$adb" -s "$serial" exec-out run-as "$package" cat "files/$app_dir/$name" > "$destination"
}

# Immutable provenance and all required inputs are checked before device mutation.
run_logged oracle-provenance bash -c "cd '$repo_root' && sha256sum --check evidence/oracle/official-10.19.0/checksums/evidence-sha256sum.txt"
run_logged task11-provenance bash -c "cd '$repo_root/evidence/oracle/official-10.19.0/fixture-execution' && sha256sum --check task-11-evidence-sha256sum.txt"
run_logged official-fixture-manifest python3 "$official_project/verify-generated-fixtures.py" "$fixtures" "$key_hash"
for name in official-10.19.0-plain.realm official-10.19.0-encrypted.realm fixture-manifest.json; do
    install -m 0444 "$fixtures/$name" "$run_dir/original/$name"
done
printf '%s\n' "$key_hex" > "$run_dir/original/fixture-key.hex"
chmod 0400 "$run_dir/original/fixture-key.hex"
sha256sum "$run_dir/original/official-10.19.0-plain.realm" "$run_dir/original/official-10.19.0-encrypted.realm" > "$run_dir/original/immutable-input.sha256"

assert_device "$fork_serial" fork
assert_device "$official_serial" official-reader
log "Fork API=$(tr -d '\r' < "$run_dir/logs/fork-api-level.log") page_size=$(tr -d '\r' < "$run_dir/logs/fork-page-size.log")"
log "Official reader API=$(tr -d '\r' < "$run_dir/logs/official-reader-api-level.log") page_size=$(tr -d '\r' < "$run_dir/logs/official-reader-page-size.log")"

# The supplied repository was already verified by the G008 lane. Never rebuild,
# use mavenLocal, or consult a remote publication endpoint from this fixture lane.
log "Using supplied fork repository $fork_repository"
run_logged fork-assemble "$repo_root/gradlew" --no-daemon --console=plain -p "$fork_project" -PforkRepository="$fork_repository" -Pandroid.aapt2FromMavenOverride="$aapt2" :app:assembleDebug :app:assembleDebugAndroidTest

# G009 supplies two adb transports to one API-37 / 16 KiB AVD. Serializing the
# whole mutable device phase prevents AC-07 from installing over another lane.
[[ "$fork_serial" == emulator-5654 && "$official_serial" == emulator-5654 ]] || {
    echo 'G009 requires emulator-5654 for both AC-07 device phases; localhost:5655 is the same AVD transport' >&2
    exit 3
}
exec 9>/tmp/realm-g009-device.lock
flock -n 9 || { echo 'Could not acquire /tmp/realm-g009-device.lock; another G009 lane owns the device' >&2; exit 3; }
log 'Acquired /tmp/realm-g009-device.lock for the complete AC-07 mutable device phase'
run_logged fork-install-app "$adb" -s "$fork_serial" install -r -t "$fork_project/app/build/outputs/apk/debug/app-debug.apk"
run_logged fork-install-test "$adb" -s "$fork_serial" install -r -t "$fork_project/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
for name in official-10.19.0-plain.realm official-10.19.0-encrypted.realm fixture-key.hex; do
    copy_to_app "$fork_serial" io.realm.fixtureac07fork ac07-original "$run_dir/original/$name"
done
run_instrumentation fork-instrumentation "$adb" -s "$fork_serial" shell am instrument -w -r -e class io.realm.fixtureoracle.ForkFixtureCompatibilityTest io.realm.fixtureac07fork.test/androidx.test.runner.AndroidJUnitRunner
for name in official-10.19.0-plain.realm official-10.19.0-encrypted.realm; do
    copy_from_app "$fork_serial" io.realm.fixtureac07fork ac07-working "$name" "$run_dir/fork-modified/$name"
done
copy_from_app "$fork_serial" io.realm.fixtureac07fork ac07-results fork-report.json "$run_dir/fork-modified/fork-report.json"
run_logged fork-export-verification python3 "$project_dir/verify-ac07-results.py" "$run_dir/original" "$run_dir/fork-modified" "$run_dir/fork-modified/fork-report.json"

# The reverse reader uses the isolated official-only project and a separate package/data sandbox.
FIXTURE_KEY_HEX="$key_hex" run_logged official-reader-assemble bash -c "cd '$official_project' && ./gradlew --no-daemon --console=plain -Pandroid.aapt2FromMavenOverride='$aapt2' :app:assembleDebug :app:assembleDebugAndroidTest"
run_logged official-reader-install-app "$adb" -s "$official_serial" install -r -t "$official_project/app/build/outputs/apk/debug/app-debug.apk"
run_logged official-reader-install-test "$adb" -s "$official_serial" install -r -t "$official_project/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
for name in official-10.19.0-plain.realm official-10.19.0-encrypted.realm; do
    copy_to_app "$official_serial" io.realm.fixtureoracle ac07-fork-modified "$run_dir/fork-modified/$name"
done
FIXTURE_KEY_HEX="$key_hex" run_instrumentation official-reverse-instrumentation "$adb" -s "$official_serial" shell am instrument -w -r -e class io.realm.fixtureoracle.OfficialFixtureOracleTest#verifyForkModifiedCopiesWithOfficialReaderWithoutMigration io.realm.fixtureoracle.test/androidx.test.runner.AndroidJUnitRunner
sha256sum "$run_dir/original/official-10.19.0-plain.realm" "$run_dir/original/official-10.19.0-encrypted.realm" > "$run_dir/original/immutable-input-after.sha256"
diff -u "$run_dir/original/immutable-input.sha256" "$run_dir/original/immutable-input-after.sha256" > "$run_dir/logs/immutable-input-diff.log"
cat > "$run_dir/RESULT.txt" <<RESULT
RESULT=PASS
AC=AC-07
INPUT_DIRECTORY=$fixtures
RUN_DIRECTORY=$run_dir
FORK_SERIAL=$fork_serial
OFFICIAL_READER_SERIAL=$official_serial
IMMUTABLE_INPUT_HASHES=original/immutable-input.sha256
FORK_REPORT=fork-modified/fork-report.json
RESULT
log "PASS AC-07; evidence chain preserved in $run_dir"
