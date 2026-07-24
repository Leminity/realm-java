#!/usr/bin/env bash
# Runs AC-08 against a local G008 stage, a validated deployment, or Maven Central.
# Device execution remains locked to the API 37 / 16 KiB acceptance gates below.
set -euo pipefail

REDACTED_VALIDATED_REPOSITORY='<redacted-validated-repository>'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LEADER_ROOT=/mnt/d/workspace/jiran/realm
PROJECT="$ROOT/compatibility-fixtures/ac08-api37-ps16k-runtime"
OFFICIAL_PROJECT="$PROJECT/official-project"
DEFAULT_REPOSITORY=/mnt/d/workspace/jiran/realm/build/g008-root-final-stage-run1
DEFAULT_SDK=/home/leminity/Android/Sdk

usage() {
  cat >&2 <<'USAGE'
usage: run-ac08.sh [--mode local|validated|validated-mirror|central] [--repository <local-stage>]
  [--repository-url <https://.../deployment/<id>/download> --bearer-env <ENV>]
  [--sdk-root <path> --serial <serial> --expected-avd <name>]
  [--official-gradle <path> --immutable-encrypted <path>]
  [--official-gradle-home-archive <path> --official-gradle-home-archive-sha256 <sha256>]
  [--gradle-user-home <empty-dir> --evidence-dir <dir> --run-id <id>]
  [--official-inputs-preflight-only]
  [--dry-run --dry-run-identity <sdk,page,avd,linker,package>]

No arguments retain the original local, offline acceptance runner behavior.
Remote modes require a caller-supplied empty Gradle home and evidence directory.
USAGE
  exit 64
}
fail() { echo "AC08 FAIL: $*" >&2; exit 1; }
require_value() { [[ $# -ge 2 && -n $2 ]] || usage; }
valid_env_name() { [[ $1 =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; }
valid_deployment_url() { [[ $1 == https://* && $1 != *'?'* && $1 != *'#'* && $1 =~ /deployment/[A-Za-z0-9._-]+/download/?$ ]]; }
valid_file_repository_url() { [[ $1 == file:///* && $1 != *'?'* && $1 != *'#'* ]]; }

MODE=local
REPOSITORY=$DEFAULT_REPOSITORY
REPOSITORY_URL=''
BEARER_ENV=''
SDK=$DEFAULT_SDK
SERIAL=emulator-5654
EXPECTED_AVD=realm-api37-ps16k-kvm
OFFICIAL_GRADLE="${AC08_OFFICIAL_GRADLE:-}"
OFFICIAL_GRADLE_HOME_ARCHIVE=''
OFFICIAL_GRADLE_HOME_ARCHIVE_SHA256=''
IMMUTABLE_ENCRYPTED="$LEADER_ROOT/compatibility-fixtures/official-10.19.0-generator/generated/official-10.19.0-oracle/official-10.19.0-encrypted.realm"
EVIDENCE_ROOT="${AC08_EVIDENCE_DIR:-$ROOT/evidence/ac08-api37-ps16k}"
EVIDENCE_EXPLICIT=false
[[ -n ${AC08_EVIDENCE_DIR:-} ]] && EVIDENCE_EXPLICIT=true
RUN_ID="${AC08_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
GRADLE_USER_HOME=''
DRY_RUN=false
DRY_RUN_IDENTITY=''
OFFICIAL_INPUTS_PREFLIGHT_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) require_value "$@"; MODE=$2; shift 2 ;;
    --repository) require_value "$@"; REPOSITORY=$2; shift 2 ;;
    --repository-url) require_value "$@"; REPOSITORY_URL=$2; shift 2 ;;
    --bearer-env) require_value "$@"; BEARER_ENV=$2; shift 2 ;;
    --sdk-root) require_value "$@"; SDK=$2; shift 2 ;;
    --serial) require_value "$@"; SERIAL=$2; shift 2 ;;
    --expected-avd) require_value "$@"; EXPECTED_AVD=$2; shift 2 ;;
    --official-gradle) require_value "$@"; OFFICIAL_GRADLE=$2; shift 2 ;;
    --official-gradle-home-archive) require_value "$@"; OFFICIAL_GRADLE_HOME_ARCHIVE=$2; shift 2 ;;
    --official-gradle-home-archive-sha256) require_value "$@"; OFFICIAL_GRADLE_HOME_ARCHIVE_SHA256=$2; shift 2 ;;
    --immutable-encrypted) require_value "$@"; IMMUTABLE_ENCRYPTED=$2; shift 2 ;;
    --gradle-user-home) require_value "$@"; GRADLE_USER_HOME=$2; shift 2 ;;
    --evidence-dir) require_value "$@"; EVIDENCE_ROOT=$2; EVIDENCE_EXPLICIT=true; shift 2 ;;
    --run-id) require_value "$@"; RUN_ID=$2; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --dry-run-identity) require_value "$@"; DRY_RUN_IDENTITY=$2; shift 2 ;;
    --official-inputs-preflight-only) OFFICIAL_INPUTS_PREFLIGHT_ONLY=true; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

[[ $MODE == local || $MODE == validated || $MODE == validated-mirror || $MODE == central ]] || usage
if [[ $OFFICIAL_INPUTS_PREFLIGHT_ONLY == false ]]; then
case "$MODE" in
  local)
    [[ -z $REPOSITORY_URL && -z $BEARER_ENV ]] || usage
    REPOSITORY="$(cd "$REPOSITORY" 2>/dev/null && pwd || true)"
    [[ -n $REPOSITORY || $DRY_RUN == true ]] || fail "missing G008 local staging repository"
    FORK_REPOSITORY_URL="file://$REPOSITORY"
    ;;
  validated)
    [[ -n $REPOSITORY_URL && -n $BEARER_ENV ]] || usage
    valid_deployment_url "$REPOSITORY_URL" || fail 'validated repository URL must be one HTTPS /deployment/<id>/download URL without query or fragment'
    valid_env_name "$BEARER_ENV" || fail 'invalid bearer environment variable name'
    BEARER_VALUE="${!BEARER_ENV:-}"
    [[ -n $BEARER_VALUE ]] || fail "validated mode requires non-empty bearer environment variable: $BEARER_ENV"
    [[ -n $GRADLE_USER_HOME && $EVIDENCE_EXPLICIT == true ]] || fail 'remote mode requires --gradle-user-home and --evidence-dir (or AC08_EVIDENCE_DIR)'
    FORK_REPOSITORY_URL=$REPOSITORY_URL
    ;;
  validated-mirror)
    [[ -n $REPOSITORY_URL && -z $BEARER_ENV ]] || usage
    valid_file_repository_url "$REPOSITORY_URL" || fail 'validated mirror repository URL must be one credential-free file URL'
    mirror_path=${REPOSITORY_URL#file://}
    [[ -d $mirror_path || $DRY_RUN == true ]] || fail "validated mirror repository does not exist: $mirror_path"
    [[ -n $GRADLE_USER_HOME && $EVIDENCE_EXPLICIT == true ]] || fail 'validated mirror mode requires --gradle-user-home and --evidence-dir'
    FORK_REPOSITORY_URL=$REPOSITORY_URL
    ;;
  central)
    [[ -z $REPOSITORY_URL && -z $BEARER_ENV ]] || usage
    [[ -n $GRADLE_USER_HOME && $EVIDENCE_EXPLICIT == true ]] || fail 'remote mode requires --gradle-user-home and --evidence-dir (or AC08_EVIDENCE_DIR)'
    FORK_REPOSITORY_URL='mavenCentral()'
    ;;
esac
fi
FORK_REPOSITORY_EVIDENCE=${FORK_REPOSITORY_URL:-}
VALIDATED_DEPLOYMENT_ID=''
if [[ $MODE == validated ]]; then
  VALIDATED_DEPLOYMENT_ID=${REPOSITORY_URL#*/deployment/}
  VALIDATED_DEPLOYMENT_ID=${VALIDATED_DEPLOYMENT_ID%/download*}
  FORK_REPOSITORY_EVIDENCE=$REDACTED_VALIDATED_REPOSITORY
fi
if [[ $MODE != local || $OFFICIAL_INPUTS_PREFLIGHT_ONLY == true ]]; then
  [[ -n $OFFICIAL_GRADLE_HOME_ARCHIVE && $OFFICIAL_GRADLE_HOME_ARCHIVE_SHA256 =~ ^[0-9a-f]{64}$ ]] ||
    fail 'remote mode requires a checksum-bound prewarmed official Gradle home archive'
fi

ADB="$SDK/platform-tools/adb"
AAPT2="$SDK/build-tools/36.0.0/aapt2"
ZIPALIGN="$SDK/build-tools/36.0.0/zipalign"
OFFICIAL_PACKAGE=io.realm.ac08.official
FORK_PACKAGE=io.realm.ac08.fork
EVIDENCE="$EVIDENCE_ROOT/$RUN_ID"
WORK="$(mktemp -d)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

if [[ $MODE != local ]]; then
  mkdir -p "$GRADLE_USER_HOME"
  if find "$GRADLE_USER_HOME" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    fail "remote Gradle user home must be empty: $GRADLE_USER_HOME"
  fi
fi
OFFICIAL_GRADLE_HOME="$HOME/.gradle"
if [[ ( $MODE != local || $OFFICIAL_INPUTS_PREFLIGHT_ONLY == true ) && $DRY_RUN != true ]]; then
  [[ -f $OFFICIAL_GRADLE_HOME_ARCHIVE ]] || fail 'missing prewarmed official Gradle home archive'
  [[ "$(sha256sum "$OFFICIAL_GRADLE_HOME_ARCHIVE" | awk '{print $1}')" == "$OFFICIAL_GRADLE_HOME_ARCHIVE_SHA256" ]] ||
    fail 'prewarmed official Gradle home archive SHA-256 mismatch'
  OFFICIAL_GRADLE_HOME="$WORK/official-gradle-home"
  mkdir -p "$OFFICIAL_GRADLE_HOME"
  python3 - "$OFFICIAL_GRADLE_HOME_ARCHIVE" "$OFFICIAL_GRADLE_HOME" <<'PY'
import pathlib, sys, tarfile
archive = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2]).resolve()
with tarfile.open(archive, 'r:*') as source:
    members = source.getmembers()
    if not members:
        raise SystemExit('official Gradle home archive is empty')
    for member in members:
        relative = pathlib.PurePosixPath(member.name)
        if relative.is_absolute() or '..' in relative.parts or not (member.isdir() or member.isfile()):
            raise SystemExit('official Gradle home archive contains an unsafe entry')
    source.extractall(destination, members=members, filter='data')
PY
  find "$OFFICIAL_GRADLE_HOME" -mindepth 1 -print -quit | grep -q . ||
    fail 'prewarmed official Gradle home archive extracted no content'
fi

print_command() {
  local arg
  for arg in "$@"; do
    if [[ $arg == G011_FORK_BEARER=* ]]; then
      printf '%q ' 'G011_FORK_BEARER=<redacted>'
    elif [[ $MODE == validated && $arg == G008_STAGING_REPOSITORY=* ]]; then
      printf '%q ' "G008_STAGING_REPOSITORY=$REDACTED_VALIDATED_REPOSITORY"
    else
      printf '%q ' "$arg"
    fi
  done
}
redact_validated_stream() {
  if [[ $MODE != validated ]]; then
    cat
    return
  fi
  python3 -c 'import sys
replacements = tuple((value.encode(), replacement) for value, replacement in ((sys.argv[1], b"<redacted-validated-repository>"), (sys.argv[2], b"<redacted-deployment-id>")) if value)
for line in sys.stdin.buffer:
    for value, replacement in replacements:
        line = line.replace(value, replacement)
    sys.stdout.buffer.write(line)
    sys.stdout.buffer.flush()' "$REPOSITORY_URL" "$VALIDATED_DEPLOYMENT_ID"
}
assert_validated_evidence_redacted() {
  [[ $MODE == validated ]] || return 0
  python3 - "$EVIDENCE" "$REPOSITORY_URL" "$VALIDATED_DEPLOYMENT_ID" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
forbidden = [value.encode() for value in sys.argv[2:] if value]
for path in root.rglob("*"):
    if path.is_file() and (
        any(value in path.read_bytes() for value in forbidden)
        or (sys.argv[3] and sys.argv[3] in path.as_posix())
    ):
        raise SystemExit(f"validated repository identifier leaked into AC08 evidence: {path}")
PY
}
run() {
  local name="$1"
  shift
  {
    printf '===== %s %s =====\n' "$name" "$(date --iso-8601=seconds)"
    printf '+ '
    print_command "$@"
    printf '\n'
    set +e
    "$@"
    local status=$?
    set -e
    printf '[exit=%s]\n' "$status"
    exit "$status"
  } 2>&1 | redact_validated_stream | tee "$EVIDENCE/${name}.log"
}
prepare_fresh_evidence() {
  local directory="$1"
  if [[ -e $directory && ! -d $directory ]]; then
    fail "evidence path is not a directory: $directory"
  fi
  if [[ -d $directory ]] && find "$directory" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    fail "evidence directory/run ID already contains evidence: $directory"
  fi
  mkdir -p "$directory"
}
write_checksums() {
  local manifest_tmp="$EVIDENCE/.SHA256SUMS.tmp"
  local verify_tmp="$EVIDENCE/.checksum-verify.tmp"
  (
    cd "$EVIDENCE"
    LC_ALL=C find . -maxdepth 1 -type f \
      ! -name SHA256SUMS ! -name checksum-verify.log \
      ! -name .SHA256SUMS.tmp ! -name .checksum-verify.tmp \
      -printf '%f\0' | LC_ALL=C sort -z | xargs -0 sha256sum
  ) > "$manifest_tmp"
  mv -f "$manifest_tmp" "$EVIDENCE/SHA256SUMS"
  if (cd "$EVIDENCE" && sha256sum -c SHA256SUMS) > "$verify_tmp"; then
    mv -f "$verify_tmp" "$EVIDENCE/checksum-verify.log"
  else
    mv -f "$verify_tmp" "$EVIDENCE/checksum-verify.log"
    return 1
  fi
}
validate_device_identity_values() {
  local sdk=$1 page=$2 avd=$3 linker=$4 compatibility=$5
  [[ "$sdk" == 37 && "$page" == 16384 && "$avd" == "$EXPECTED_AVD" && "$linker" == fatal && "$compatibility" == true ]]
}
verify_official_inputs() {
  local fixture_manifest expected_encrypted_hash actual_encrypted_hash gradle_version
  fixture_manifest="$ROOT/compatibility-fixtures/official-10.19.0-generator/generated/official-10.19.0-oracle/fixture-manifest.json"
  [[ -x "$AAPT2" ]] || fail "expected aapt2 at $AAPT2"
  [[ -x "$OFFICIAL_GRADLE" ]] || fail 'missing Gradle 7.5 required by the immutable official 10.19.0 plugin'
  gradle_version="$("$OFFICIAL_GRADLE" -g "$OFFICIAL_GRADLE_HOME" --version --no-daemon | sed -n 's/^Gradle //p' | head -1)"
  [[ $gradle_version == 7.5 ]] || fail "official baseline requires exact Gradle 7.5, found: ${gradle_version:-unknown}"
  [[ -f "$IMMUTABLE_ENCRYPTED" ]] || fail 'missing immutable encrypted official input'
  expected_encrypted_hash="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["encrypted_fixture_sha256"])' "$fixture_manifest")"
  [[ $expected_encrypted_hash =~ ^[0-9a-f]{64}$ ]] || fail 'official fixture manifest lacks encrypted fixture SHA-256'
  actual_encrypted_hash="$(sha256sum "$IMMUTABLE_ENCRYPTED" | awk '{print $1}')"
  [[ $actual_encrypted_hash == "$expected_encrypted_hash" ]] || fail 'immutable encrypted official input SHA-256 mismatch'
}
require_instrumentation_pass() {
  local name="$1"
  local log="$EVIDENCE/${name}.log"
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
  local remote_name="$1" destination="$2"
  "$ADB" -s "$SERIAL" exec-out run-as "$FORK_PACKAGE" cat "files/ac08/$remote_name" > "$destination"
}
wait_for_fork_file() {
  local remote_name="$1" destination="$2" attempt
  for attempt in $(seq 1 120); do
    if capture_fork_file "$remote_name" "$destination" 2>/dev/null && grep -Eq '^pid=[1-9][0-9]*$' "$destination"; then
      cat "$destination"; return 0
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
  validate_device_identity_values "$sdk" "$page" "$avd" "$linker" "$compatibility"
  printf 'SDK=%s PAGE_SIZE=%s AVD=%s linker_compat=%s package_compat_disabled=%s\n' "$sdk" "$page" "$avd" "$linker" "$compatibility"
}

if [[ $OFFICIAL_INPUTS_PREFLIGHT_ONLY == true ]]; then
  [[ $DRY_RUN == false ]] || fail 'official input preflight cannot be a dry run'
  verify_official_inputs
  env ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK" \
    "$OFFICIAL_GRADLE" -g "$OFFICIAL_GRADLE_HOME" -p "$OFFICIAL_PROJECT" \
    --project-cache-dir "$WORK/official-project-cache" \
    --offline --no-daemon --console=plain \
    -Pandroid.aapt2FromMavenOverride="$AAPT2" \
    clean :official-app:assembleDebug :official-app:assembleDebugAndroidTest
  printf 'AC08_OFFICIAL_INPUTS_PREFLIGHT=PASS\n'
  exit 0
fi

prepare_fresh_evidence "$EVIDENCE"
{
  printf 'run_id=%s\nmode=%s\nrepository=%s\nserial=%s\nexpected_avd=%s\n' "$RUN_ID" "$MODE" "$FORK_REPOSITORY_EVIDENCE" "$SERIAL" "$EXPECTED_AVD"
  [[ $MODE != local ]] && printf 'gradle_user_home=%s\n' "$GRADLE_USER_HOME"
  [[ $MODE != local ]] && printf 'official_gradle_home_archive_sha256=%s\n' "$OFFICIAL_GRADLE_HOME_ARCHIVE_SHA256"
  printf 'bearer=redacted\n'
} > "$EVIDENCE/run-metadata.txt"
if [[ $DRY_RUN == true ]]; then
  identity=${DRY_RUN_IDENTITY:-"37,16384,$EXPECTED_AVD,fatal,true"}
  IFS=, read -r sdk page avd linker compatibility extra <<< "$identity"
  [[ -z ${extra:-} && -n ${compatibility:-} ]] || fail 'dry-run identity must be sdk,page,avd,linker,package-compatibility'
  validate_device_identity_values "$sdk" "$page" "$avd" "$linker" "$compatibility" || fail "dry-run rejected device identity: $identity"
  {
    printf 'DRY_RUN=PASS\n'
    printf 'fork_repository_mode=%s\n' "$MODE"
    printf 'fork_repository=%s\n' "$FORK_REPOSITORY_EVIDENCE"
    printf 'exclusive_buildscript_routing=PASS\nexclusive_dependency_routing=PASS\n'
    if [[ $MODE != local ]]; then
      printf 'official_build_command=%q -g %q -p %q --offline --no-daemon --console=plain\n' \
        "$OFFICIAL_GRADLE" '<extracted-checksum-bound-official-home>' "$OFFICIAL_PROJECT"
      printf 'official_and_fork_gradle_homes=SEPARATE\n'
    fi
    printf 'fork_build_command='
    if [[ $MODE == local ]]; then
      printf 'env G011_REPOSITORY_MODE=local G008_STAGING_REPOSITORY=%q ' "$FORK_REPOSITORY_URL"
    elif [[ $MODE == validated ]]; then
      printf 'env G011_REPOSITORY_MODE=validated G008_STAGING_REPOSITORY=%q G011_FORK_BEARER=<redacted> GRADLE_USER_HOME=%q ' "$FORK_REPOSITORY_EVIDENCE" "$GRADLE_USER_HOME"
    elif [[ $MODE == validated-mirror ]]; then
      printf 'env G011_REPOSITORY_MODE=validated-mirror G008_STAGING_REPOSITORY=%q GRADLE_USER_HOME=%q ' "$FORK_REPOSITORY_URL" "$GRADLE_USER_HOME"
    else
      printf 'env G011_REPOSITORY_MODE=central GRADLE_USER_HOME=%q ' "$GRADLE_USER_HOME"
    fi
    printf '%q -p %q --no-daemon --console=plain ' "$ROOT/gradlew" "$PROJECT"
    [[ $MODE == local ]] && printf '%s ' '--offline'
    printf ':fork-app:assembleDebug :fork-app:assembleDebugAndroidTest\n'
    printf 'fork_apk_zipalign_command=%q -c -P 16 -v 4 %q\n' \
      "$ZIPALIGN" "$PROJECT/fork-app/build/outputs/apk/debug/fork-app-debug.apk"
    printf 'device_identity=SDK=%s PAGE_SIZE=%s AVD=%s linker=%s package_compatibility=%s\n' "$sdk" "$page" "$avd" "$linker" "$compatibility"
  } > "$EVIDENCE/dry-run-command-plan.txt"
  printf 'AC08=DRY_RUN_PASS\n' > "$EVIDENCE/result.txt"
  assert_validated_evidence_redacted
  write_checksums
  exit 0
fi

[[ -x "$ADB" ]] || fail "expected adb at $ADB"
[[ -x "$AAPT2" ]] || fail "expected aapt2 at $AAPT2"
[[ -x "$ZIPALIGN" ]] || fail "expected zipalign at $ZIPALIGN"
if [[ $MODE == local ]]; then
  [[ -d "$REPOSITORY/io/github/leminity/realm" ]] || fail "missing G008 local staging repository: $REPOSITORY"
fi
if [[ -z "$OFFICIAL_GRADLE" ]]; then
  OFFICIAL_GRADLE="$(find "$HOME/.gradle/wrapper/dists/gradle-7.5-all" -type f -path '*/bin/gradle' -print -quit 2>/dev/null || true)"
fi
[[ -x "$OFFICIAL_GRADLE" ]] || fail 'missing cached Gradle 7.5 required by the immutable official 10.19.0 plugin'
verify_official_inputs

run official-build-offline \
  env ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK" \
  "$OFFICIAL_GRADLE" -g "$OFFICIAL_GRADLE_HOME" -p "$OFFICIAL_PROJECT" --offline --no-daemon --console=plain \
  -Pandroid.aapt2FromMavenOverride="$AAPT2" \
  :official-app:assembleDebug :official-app:assembleDebugAndroidTest
fork_env=(env "G011_REPOSITORY_MODE=$MODE")
[[ $MODE != central ]] && fork_env+=("G008_STAGING_REPOSITORY=$FORK_REPOSITORY_URL")
[[ $MODE == validated ]] && fork_env+=("G011_FORK_BEARER=$BEARER_VALUE")
fork_gradle=("$ROOT/gradlew")
[[ $MODE != local ]] && fork_gradle+=(-g "$GRADLE_USER_HOME")
fork_gradle+=(-p "$PROJECT" --no-daemon --console=plain)
[[ $MODE == local ]] && fork_gradle+=(--offline)
[[ $MODE != local ]] && fork_env+=("GRADLE_USER_HOME=$GRADLE_USER_HOME")
run "fork-build-$MODE" "${fork_env[@]}" "${fork_gradle[@]}" :fork-app:assembleDebug :fork-app:assembleDebugAndroidTest
run "fork-resolution-$MODE" "${fork_env[@]}" "${fork_gradle[@]}" :fork-app:dependencies --configuration debugRuntimeClasspath
grep -Fq 'io.github.leminity.realm:realm-android-library:10.19.0-agp9.2' "$EVIDENCE/fork-resolution-$MODE.log" ||
  fail "fork runtime did not resolve expected artifact in $MODE mode"
if [[ $MODE == local ]]; then
  run g008-artifact-manifest find "$REPOSITORY/io/github/leminity/realm" -type f -maxdepth 6 -print
else
  printf 'remote_repository=%s\nexact_fork_routing=PASS\n' "$FORK_REPOSITORY_EVIDENCE" > "$EVIDENCE/fork-repository-routing.txt"
fi
if grep -Rqi 'jitpack\.io' "$PROJECT"/*.gradle "$PROJECT"/*/build.gradle "$PROJECT"/*/settings.gradle; then
  fail 'AC-08 harness must not configure JitPack'
fi

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
run fork-apk-zipalign "$ZIPALIGN" -c -P 16 -v 4 "$FORK_APK"

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

printf 'AC08=PASS\n' | tee "$EVIDENCE/result.txt"
assert_validated_evidence_redacted
write_checksums
