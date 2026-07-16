#!/usr/bin/env bash
# Validates the exact source and recursive-submodule provenance baseline.
set -euo pipefail

readonly EXPECTED_COMMIT=0ab8d6961afb038d0e0c69478de45dda3958d641
readonly EXPECTED_TAG=v10.19.0
readonly EXPECTED_CORE=5533505d18fda93a7a971d58a191db5005583c92
readonly EXPECTED_CATCH=3f0283de7a9c43200033da996ff9093be3ac84dc
readonly EXPECTED_SHA1=d9ae30f34095107ece9dceb224839f0dc2f9c1c7
readonly EXPECTED_SHA2=0e9aebf34101c6aa89355fd76ac9cd886735dee1
readonly REQUIRED_GRADLE_URL='https\://services.gradle.org/distributions/gradle-9.6.1-bin.zip'
readonly REQUIRED_GRADLE_SHA256=9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14
readonly -a APPROVED_WRAPPER_PATHS=(
  examples/gradle/wrapper/gradle-wrapper.properties
  gradle-plugin/gradle/wrapper/gradle-wrapper.properties
  gradle/wrapper/gradle-wrapper.properties
  library-benchmarks/gradle/wrapper/gradle-wrapper.properties
  library-build-transformer/gradle/wrapper/gradle-wrapper.properties
  realm-annotations/gradle/wrapper/gradle-wrapper.properties
  realm-transformer/gradle/wrapper/gradle-wrapper.properties
  realm/gradle/wrapper/gradle-wrapper.properties
)

# Each entry is tied to a recorded G003 failure or its approved G004
# Transformer prerequisite. Keep this exact-path list rather than widening a
# parent directory: provenance verification must still reject unrelated source,
# build, and evidence changes.
readonly -a APPROVED_G003_PATHS=(
  build.gradle
  dependencies.list
  evidence/audit/g003-stage2-configuration-review.md
  evidence/g003/F001-realm-annotations-help-after.log
  evidence/g003/F001-realm-annotations-help-before.log
  evidence/g003/F002-realm-annotations-help-after.log
  evidence/g003/F003-realm-annotations-help-after.log
  evidence/g003/F004-realm-annotations-help-after.log
  evidence/g003/F005-realm-transformer-help-after.log
  evidence/g003/F005-realm-transformer-help-before.log
  evidence/g003/F006-realm-transformer-help-after.log
  evidence/g003/F007-realm-transformer-help-after.log
  evidence/g003/F008-realm-transformer-help-after.log
  evidence/g003/F009-realm-transformer-test-after.log
  evidence/g003/F009-realm-transformer-test-before.log
  evidence/g003/F010-realm-transformer-test-after.log
  evidence/g003/F011-library-build-transformer-help-after.log
  evidence/g003/F011-library-build-transformer-help-before.log
  evidence/g003/F012-library-build-transformer-help-after.log
  evidence/g003/F013-library-build-transformer-test-after.log
  evidence/g003/F014-realm-help-after.log
  evidence/g003/F014-realm-help-before.log
  evidence/g003/F015-realm-help-after.log
  evidence/g003/F016-realm-help-after.log
  evidence/g003/F017-realm-help-after.log
  evidence/g003/F018-realm-help-after-agp9-kotlin-sdk-config.log
  evidence/g003/F019-realm-help-after-legacy-kapt-and-sdk-dsl.log
  evidence/g003/F020-baseextension-before.log
  evidence/g003/F020-realm-help-after-public-archives-name.log
  evidence/g003/F021-realm-help-after-built-in-kotlin-options.log
  evidence/g003/F021-sdkcomponents-extension-after.log
  evidence/g003/F021-sdkcomponents-extension-before.log
  evidence/g003/F022-realm-help-after-jar-archive-classifiers.log
  evidence/g003/F022-transform-execution-after.log
  evidence/g003/F023-realm-help-after-namespaces.log
  evidence/g003/F024-realm-help-after-processor-java-api.log
  evidence/g003/F025-realm-help-after-sdk-components-bootclasspath.log
  evidence/g003/F026-realm-help-after-lazy-bootclasspath.log
  evidence/g003/F027-realm-help-after-lazy-sdk-provider.log
  evidence/g003/F028-realm-help-after-spotbugs-report-config.log
  evidence/g003/F029-realm-help-after-report-required-api.log
  evidence/g003/F030-root-help-after-maven-central.log
  evidence/g003/F031-root-help-after-gradlebuild-dir.log
  evidence/g003/F032-root-help-after-archive-api.log
  evidence/g003/F033-root-installRealmJava-dry-run.log
  evidence/g003/F034-gradle-plugin-help-before.log
  evidence/g003/F035-gradle-plugin-help-after-repository-internal-api.log
  evidence/g003/F036-gradle-plugin-help-after-java-extension.log
  evidence/g003/F037-gradle-plugin-pom-after-help.log
  evidence/g003/F038-gradle-plugin-test-before-fixture-compat.log
  evidence/g003/F039-gradle-plugin-test-after-kotlin-target.log
  evidence/g003/F040-root-installTransformer-for-plugin-test.log
  evidence/g003/F041-root-installTransformer-after-signing-gate.log
  evidence/g003/F042-root-installTransformer-after-sourcesjar-dependency.log
  evidence/g003/F043-gradle-plugin-test-after-current-transformer.log
  evidence/g003/F044-realm-help-after-buildconfig.log
  evidence/g003/F045-realm-help-after-metadata-config-prerequisite.log
  evidence/g003/F046-realm-tasks-after-help.log
  evidence/g003/F047-realm-base-pom-before-qualified-metadata-gate.log
  evidence/g003/F048-realm-base-kotlin-pom-after-qualified-gate.log
  evidence/g003/F049-realm-processor-test-metadata-after-qualified-gate.log
  evidence/g003/F050-realm-base-kotlin-pom-after-publication-task-names.log
  evidence/g003/F051-realm-processor-test-metadata-after-publication-task-names.log
  evidence/g003/F052-realm-processor-test-after-native-dependency-removal.log
  evidence/g003/F053-realm-processor-test-after-deprecation-error-suppression.log
  evidence/g003/F054-realm-processor-test-after-nonnative-fixture.log
  evidence/g003/F055-root-installRealmJava-dry-run-post-processor.log
  evidence/g003/G004-post-integration-matrix.log
  gradle-plugin/build.gradle
  gradle-plugin/src/test/groovy/io/realm/gradle/PluginTest.groovy
  library-build-transformer/build.gradle
  mavencentral-publications.gradle
  realm-annotations/build.gradle
  realm-transformer/build.gradle
  realm-transformer/src/main/kotlin/io/realm/transformer/RealmTransformer.kt
  realm-transformer/src/main/kotlin/io/realm/transformer/ext/ProjectExt.kt
  realm/build.gradle
  realm/kotlin-extensions/build.gradle
  realm/realm-annotations-processor/build.gradle
  realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/CamelCaseConverter.kt
  realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/LowerCaseWithSeparatorConverter.kt
  realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/PascalCaseConverter.kt
  realm/realm-library/build.gradle
  tools/test-verify-g004-transformer-public-api.sh
  tools/verify-g004-transformer-public-api.sh
)

is_baseline_allowed_path() {
  local path="$1"
  local approved_path

  for approved_path in "${APPROVED_G003_PATHS[@]}"; do
    [[ "$path" == "$approved_path" ]] && return 0
  done

  # These are deliberately exact G001/G002 non-production surfaces. Do not
  # replace them with parent-directory wildcards: fixture source is confined to
  # one isolated harness and evidence is confined to its recorded version/root.
  case "$path" in
    .gitignore|compatibility-change-ledger.md|production-diff-ledger.md|\
    evidence/provenance/*|\
    evidence/oracle/official-10.19.0/*|\
    evidence/toolchain/android17-wsl2/*|\
    evidence/toolchain/task-12-api37-runtime-audit/*|\
    evidence/audit/g002-toolchain-final.md|\
    evidence/audit/g003-independent-build-recovery.md|\
    evidence/audit/task-9-preflight.md|\
    compatibility-fixtures/official-10.19.0-generator/*|\
    tools/capture-baseline.py|tools/verify-baseline.sh|\
    tools/verify-release-tag.sh|tools/test-verify-release-tag.sh|\
    tools/bootstrap-wsl-android.sh|tools/verify-toolchain.sh|\
    tools/verify-g003-independent-builds.sh|\
    tools/test-verify-g003-independent-builds.sh|\
    tools/test-verify-baseline.sh|\
    examples/gradle/wrapper/gradle-wrapper.properties|\
    gradle-plugin/gradle/wrapper/gradle-wrapper.properties|\
    gradle/wrapper/gradle-wrapper.properties|\
    library-benchmarks/gradle/wrapper/gradle-wrapper.properties|\
    library-build-transformer/gradle/wrapper/gradle-wrapper.properties|\
    realm-annotations/gradle/wrapper/gradle-wrapper.properties|\
    realm-transformer/gradle/wrapper/gradle-wrapper.properties|\
    realm/gradle/wrapper/gradle-wrapper.properties)
      return 0
      ;;
  esac

  return 1
}

is_approved_wrapper_pin() {
  [[ "$1" == "$REQUIRED_GRADLE_URL" && "$2" == "$REQUIRED_GRADLE_SHA256" ]]
}

verify_approved_wrapper_pins() {
  local wrapper url sha

  for wrapper in "${APPROVED_WRAPPER_PATHS[@]}"; do
    url="$(sed -n 's/^distributionUrl=//p' "$wrapper")"
    sha="$(sed -n 's/^distributionSha256Sum=//p' "$wrapper")"
    if ! is_approved_wrapper_pin "$url" "$sha"; then
      printf 'unexpected Gradle wrapper pin in %s\n' "$wrapper" >&2
      return 1
    fi
  done
}

verify_baseline_capture() {
  local baseline="$1"
  local current="$2"

  python3 - "$baseline" "$current" <<'PY'
import json
import sys

baseline_path, current_path = sys.argv[1:]
with open(baseline_path, encoding="utf-8") as source:
    baseline = json.load(source)
with open(current_path, encoding="utf-8") as source:
    current = json.load(source)

# The worktree branch is execution context, not immutable provenance. This
# lets a detached Team worktree validate the same source/tag/submodule tree.
baseline["source"].pop("work_branch", None)
current["source"].pop("work_branch", None)

# These G003 toolchain changes are pinned, not broadly ignored. The path
# allowlist above permits the corresponding dependencies.list edit; these
# checks retain its exact approved values and digest in the provenance capture.
approved_toolchain_pins = {
    "GRADLE_BUILD_TOOLS": "9.1.1",
    "gradle": "9.6.1",
    "ndkVersion": "29.0.14206865",
    "KOTLIN": "2.2.10",
}
approved_dependencies_sha256 = "1ab17f0b75665a98d38d73dc81eba601d438b1be2aa6d3f3ece994e43664394b"
for key, expected in approved_toolchain_pins.items():
    actual = current["toolchain_pins"].get(key)
    if actual != expected:
        print(f"unexpected approved G003 toolchain pin {key}: {actual!r}", file=sys.stderr)
        raise SystemExit(1)
    baseline["toolchain_pins"][key] = actual

actual_dependencies_sha256 = current["source_integrity"]["dependencies_list_sha256"]
if actual_dependencies_sha256 != approved_dependencies_sha256:
    print("unexpected approved G003 dependencies.list digest", file=sys.stderr)
    raise SystemExit(1)
baseline["source_integrity"]["dependencies_list_sha256"] = actual_dependencies_sha256

# Wrapper URLs deliberately advance from the immutable v10.19.0 baseline to
# the exact G002 pins. Every remaining captured field must remain
# byte-for-value equivalent after JSON parsing.
baseline.pop("wrappers", None)
current.pop("wrappers", None)
if baseline != current:
    print("immutable baseline capture differs outside approved wrapper pins", file=sys.stderr)
    raise SystemExit(1)
PY
}

main() {
  local root path core
  local -a invalid_paths=()

  root="$(git rev-parse --show-toplevel)"
  cd "$root"

  [[ "$(git rev-parse "${EXPECTED_TAG}^{commit}")" == "$EXPECTED_COMMIT" ]]
  git merge-base --is-ancestor "$EXPECTED_COMMIT" HEAD
  [[ "$(git remote get-url upstream)" == "https://github.com/realm/realm-java.git" ]]
  [[ "$(git remote get-url origin)" == "https://github.com/Leminity/realm-java.git" ]]

  while IFS= read -r path; do
    is_baseline_allowed_path "$path" || invalid_paths+=("$path")
  done < <(git diff --name-only "$EXPECTED_COMMIT...HEAD")
  if ((${#invalid_paths[@]})); then
    printf 'non-baseline path(s) changed since %s:\n' "$EXPECTED_TAG" >&2
    printf '  %s\n' "${invalid_paths[@]}" >&2
    exit 1
  fi

  [[ "$(git -C realm/realm-library/src/main/cpp/realm-core rev-parse HEAD)" == "$EXPECTED_CORE" ]]
  core=realm/realm-library/src/main/cpp/realm-core
  [[ "$(git -C "$core/external/catch" rev-parse HEAD)" == "$EXPECTED_CATCH" ]]
  [[ "$(git -C "$core/src/external/sha-1" rev-parse HEAD)" == "$EXPECTED_SHA1" ]]
  [[ "$(git -C "$core/src/external/sha-2" rev-parse HEAD)" == "$EXPECTED_SHA2" ]]

  python3 tools/capture-baseline.py --output /tmp/realm-baseline-verify.json
  verify_baseline_capture evidence/provenance/baseline.json /tmp/realm-baseline-verify.json
  verify_approved_wrapper_pins
  rm -f /tmp/realm-baseline-verify.json
  tools/test-verify-release-tag.sh

  echo 'baseline provenance verification: PASS'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
