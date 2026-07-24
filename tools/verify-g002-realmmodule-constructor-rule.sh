#!/usr/bin/env bash
# Verifies the G002 RealmModule constructor consumer rule from source through R8.
set -euo pipefail

readonly EXPECTED_AGP='9.1.1'
readonly EXPECTED_GRADLE='9.6.1'
readonly EXPECTED_RULE='-keep @io.realm.annotations.RealmModule class * {
    <init>(...);
}'
readonly FORK_GROUP='io.github.leminity.realm'

root="${ROOT_OVERRIDE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
mode='source'

fail() {
  printf 'G002 RealmModule constructor verification: %s\n' "$*" >&2
  exit 1
}

require_file() {
  [[ -f "$1" ]] || fail "missing required file: $1"
}

verify_exact_rule() {
  local label=$1 file=$2
  python3 - "$label" "$file" "$EXPECTED_RULE" <<'PY'
import pathlib
import sys

label, path, expected = sys.argv[1:]
text = pathlib.Path(path).read_text(encoding="utf-8")
count = text.count(expected)
if count != 1:
    raise SystemExit(
        f"G002 RealmModule constructor verification: "
        f"{label} must contain the exact constructor rule once, found {count}"
    )
PY
}

verify_source() {
  local rules="$root/realm/realm-library/proguard-rules-consumer-common.pro"
  require_file "$rules"
  verify_exact_rule 'consumer-rule source' "$rules"
  python3 - "$rules" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
for description, pattern in (
    (
        "broad annotated-class member keep",
        r"-keep\s+@io\.realm\.annotations\.RealmModule\s+class\s+\*\s*"
        r"\{\s*\*\s*;\s*\}",
    ),
    (
        "broad io.realm.** member keep",
        r"-keep(?:,\S+)*\s+class\s+io\.realm\.\*\*\s*\{\s*\*\s*;\s*\}",
    ),
):
    if re.search(pattern, text):
        raise SystemExit(
            "G002 RealmModule constructor verification: "
            f"consumer-rule source contains a {description}"
        )
PY
  printf 'G002 TS-01 exact consumer-rule source: PASS\n'
}

verify_fixture_contract() {
  local fixture="$root/compatibility-fixtures/g002-realmmodule-minify"
  require_file "$fixture/build.gradle"
  require_file "$fixture/app/build.gradle"
  require_file "$fixture/app/src/main/java/io/realm/DefaultRealmModule.java"
  grep -Fq "classpath 'com.android.tools.build:gradle:$EXPECTED_AGP'" "$fixture/build.gradle" ||
    fail "fixture is not pinned to AGP $EXPECTED_AGP"
  grep -Fq 'minifyEnabled true' "$fixture/app/build.gradle" ||
    fail 'fixture release build is not minified'
  grep -Fq '@RealmModule' "$fixture/app/src/main/java/io/realm/DefaultRealmModule.java" ||
    fail 'fixture does not define the generated-like Realm module'
  if find "$fixture" -path '*/build' -prune -o \
      -type f \( -iname '*proguard*' -o -iname '*r8*' \) -print -quit | grep -q .; then
    fail 'fixture must not contain an application-local keep rule'
  fi
}

run_project_gradle() {
  local label=$1 directory=$2
  shift 2
  printf 'G002 %s: %s\n' "$label" "$*"
  (
    cd "$root/$directory"
    ./gradlew --no-daemon --console=plain --stacktrace \
      --gradle-user-home "$gradle_user_home" \
      "-Dmaven.repo.local=$candidate_repository" \
      -Pg008StagingRepository="$candidate_repository" "$@"
  )
}

stage_candidate() {
  run_project_gradle annotations-local-stage realm-annotations publishToMavenLocal
  run_project_gradle transformer-local-stage realm-transformer publishToMavenLocal
  run_project_gradle build-transformer-local-stage library-build-transformer publishToMavenLocal
  run_project_gradle realm-base-local-stage realm :realm-library:publishBasePublicationToMavenLocal
}

extract_packaged_rules() {
  local aar=$1 output=$2
  python3 - "$aar" "$output" <<'PY'
import pathlib
import sys
import zipfile

archive, output = map(pathlib.Path, sys.argv[1:])
with zipfile.ZipFile(archive) as bundle:
    try:
        rules = bundle.read("proguard.txt")
    except KeyError as error:
        raise SystemExit(
            "G002 RealmModule constructor verification: "
            f"{archive} does not package proguard.txt"
        ) from error
output.write_bytes(rules)
PY
}

verify_packaged_aar() {
  local version=$1
  local aar="$candidate_repository/${FORK_GROUP//.//}/realm-android-library/$version/realm-android-library-$version.aar"
  local packaged_rules="$work_dir/packaged-proguard.txt"
  require_file "$aar"
  extract_packaged_rules "$aar" "$packaged_rules"
  verify_exact_rule 'packaged AAR proguard.txt' "$packaged_rules"
  aar_sha256="$(sha256sum "$aar" | awk '{print $1}')"
  printf 'G002 TS-02 packaged AAR consumer metadata: PASS (%s, sha256=%s)\n' "$aar" "$aar_sha256"
}

find_apkanalyzer() {
  local sdk_dir candidate
  sdk_dir="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"
  if command -v apkanalyzer >/dev/null 2>&1; then
    command -v apkanalyzer
    return
  fi
  candidate="$sdk_dir/cmdline-tools/latest/bin/apkanalyzer"
  [[ -x "$candidate" ]] || fail 'apkanalyzer is required for DEX constructor inspection'
  printf '%s\n' "$candidate"
}

verify_minified_fixture() {
  local version=$1
  local fixture="$root/compatibility-fixtures/g002-realmmodule-minify"
  local log="$work_dir/minified-fixture.log"
  local mapping="$fixture/app/build/outputs/mapping/release/mapping.txt"
  local usage="$fixture/app/build/outputs/mapping/release/usage.txt"
  local configuration="$fixture/app/build/outputs/mapping/release/configuration.txt"
  local apk="$fixture/app/build/outputs/apk/release/app-release-unsigned.apk"
  local dex_output apkanalyzer

  (
    cd "$fixture"
    "$root/realm/gradlew" --no-daemon --console=plain --stacktrace \
      --gradle-user-home "$gradle_user_home" \
      "-PcandidateRepository=$candidate_repository" \
      "-PrealmVersion=$version" \
      clean :app:assembleRelease
  ) >"$log" 2>&1 || {
    cat "$log" >&2
    fail 'minified repository fixture build failed'
  }

  grep -Fq "Gradle $EXPECTED_GRADLE" "$log" ||
    grep -Fqx "distributionUrl=https\\://services.gradle.org/distributions/gradle-$EXPECTED_GRADLE-bin.zip" \
      "$root/realm/gradle/wrapper/gradle-wrapper.properties" ||
    fail "fixture did not use Gradle $EXPECTED_GRADLE"
  require_file "$mapping"
  require_file "$usage"
  require_file "$configuration"
  require_file "$apk"

  python3 - "$configuration" "realm-android-library-$version/proguard.txt" "$EXPECTED_RULE" <<'PY'
import pathlib
import sys

configuration = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
candidate_artifact = sys.argv[2]
expected = sys.argv[3]
if expected not in configuration:
    raise SystemExit(
        "G002 RealmModule constructor verification: merged R8 configuration "
        "does not contain the candidate AAR rule"
    )
window = configuration[max(0, configuration.index(expected) - 1000):
                       configuration.index(expected) + len(expected) + 1000]
if candidate_artifact not in window.replace("\\\\", "/"):
    raise SystemExit(
        "G002 RealmModule constructor verification: merged R8 configuration "
        "does not attribute the rule to the resolved candidate AAR"
    )
PY

  python3 - "$mapping" "$usage" <<'PY'
import pathlib
import re
import sys

mapping = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
usage = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
match = re.search(
    r"(?ms)^io\.realm\.DefaultRealmModule -> [^:]+:\n"
    r"(?P<body>.*?)(?=^[^ #].* -> [^:]+:$|\Z)",
    mapping,
)
if match is None or "<init>" not in match.group("body"):
    raise SystemExit(
        "G002 RealmModule constructor verification: mapping does not retain "
        "io.realm.DefaultRealmModule.<init>"
    )
removed = re.search(
    r"(?ms)^io\.realm\.DefaultRealmModule:\n"
    r"(?P<body>.*?)(?=^\S|\Z)",
    usage,
)
if removed is not None and "<init>" in removed.group("body"):
    raise SystemExit(
        "G002 RealmModule constructor verification: R8 usage reports "
        "io.realm.DefaultRealmModule.<init> as removed"
    )
PY

  apkanalyzer="$(find_apkanalyzer)"
  dex_output="$work_dir/default-module.dex.txt"
  "$apkanalyzer" dex code --class io.realm.DefaultRealmModule "$apk" >"$dex_output"
  grep -Fq '<init>()V' "$dex_output" ||
    fail 'DEX does not retain io.realm.DefaultRealmModule.<init>()'

  printf 'G002 TS-03 minified AGP %s/Gradle %s fixture: PASS\n' \
    "$EXPECTED_AGP" "$EXPECTED_GRADLE"
}

cleanup() {
  if [[ -n "${work_dir:-}" && -d "$work_dir" ]]; then
    rm -rf "$work_dir"
  fi
}

run_integration() {
  verify_fixture_contract
  work_dir="$(mktemp -d)"
  candidate_repository="$work_dir/maven-repository"
  gradle_user_home="${G002_GRADLE_USER_HOME:-$work_dir/gradle-user-home}"
  mkdir -p "$candidate_repository" "$gradle_user_home"
  trap cleanup EXIT

  stage_candidate
  version="$(tr -d '[:space:]' < "$root/version.txt")"
  verify_packaged_aar "$version"
  verify_minified_fixture "$version"
  cleanup
  trap - EXIT
}

main() {
  case "${1:-}" in
    '') ;;
    --run) mode='run' ;;
    *) fail 'usage: tools/verify-g002-realmmodule-constructor-rule.sh [--run]' ;;
  esac

  verify_source
  verify_fixture_contract
  if [[ "$mode" == run ]]; then
    run_integration
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
