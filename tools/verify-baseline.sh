#!/usr/bin/env bash
# Modified by Leminity from the upstream Realm Java project.
# Validates the exact source and recursive-submodule provenance baseline.
set -euo pipefail

readonly EXPECTED_COMMIT=0ab8d6961afb038d0e0c69478de45dda3958d641
readonly EXPECTED_TAG=v10.19.0
readonly EXPECTED_APPROVED_FORK_ROOT=117f0bee2cdea2c4bf75c7d3226dd389a21439bc
readonly EXPECTED_BASELINE_CORE=5533505d18fda93a7a971d58a191db5005583c92
readonly EXPECTED_FORK_CORE=a5b7ed7bb8f0db4d362c7e45b2f38358a4aeab47
readonly EXPECTED_CATCH=3f0283de7a9c43200033da996ff9093be3ac84dc
readonly EXPECTED_SHA1=d9ae30f34095107ece9dceb224839f0dc2f9c1c7
readonly EXPECTED_SHA2=0e9aebf34101c6aa89355fd76ac9cd886735dee1
readonly EXPECTED_BASELINE_SHA256=108faef7fd345d015cb60dded9712b80f893bbe36c46ef4054c62e499966dcbe
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

# These are the exact 37 entries modified between upstream v10.19.0 and the
# independently reviewed fork root. Keeping them separate makes the approved
# source boundary testable as an exact set, including the immutable Core gitlink.
readonly -a APPROVED_FORK_MODIFIED_PATHS=(
  .gitignore
  .gitmodules
  README.md
  build.gradle
  dependencies.list
  examples/gradle/wrapper/gradle-wrapper.properties
  gradle-plugin/build.gradle
  gradle-plugin/gradle/wrapper/gradle-wrapper.properties
  gradle-plugin/src/main/kotlin/io/realm/gradle/Realm.kt
  gradle-plugin/src/test/groovy/io/realm/gradle/PluginTest.groovy
  gradle/wrapper/gradle-wrapper.properties
  library-benchmarks/gradle/wrapper/gradle-wrapper.properties
  library-build-transformer/build.gradle
  library-build-transformer/gradle/wrapper/gradle-wrapper.properties
  library-build-transformer/src/main/kotlin/io/realm/buildtransformer/RealmBuildTransformer.kt
  mavencentral-properties.gradle
  mavencentral-publications.gradle
  mavencentral-publish.gradle
  realm-annotations/build.gradle
  realm-annotations/gradle/wrapper/gradle-wrapper.properties
  realm-transformer/build.gradle
  realm-transformer/gradle/wrapper/gradle-wrapper.properties
  realm-transformer/src/main/kotlin/io/realm/transformer/RealmTransformer.kt
  realm-transformer/src/main/kotlin/io/realm/transformer/ext/ProjectExt.kt
  realm/build.gradle
  realm/gradle/wrapper/gradle-wrapper.properties
  realm/kotlin-extensions/build.gradle
  realm/realm-annotations-processor/build.gradle
  realm/realm-annotations-processor/src/main/java/io/realm/processor/RealmProcessor.kt
  realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/CamelCaseConverter.kt
  realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/LowerCaseWithSeparatorConverter.kt
  realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/PascalCaseConverter.kt
  realm/realm-library/build.gradle
  realm/realm-library/src/main/cpp/realm-core
  tools/publish_release.sh
  tools/release.sh
  version.txt
)

# The independently reviewed root above cryptographically binds the complete
# G001-G013 source/evidence history. Only these exact post-review remediation
# paths may differ from that root. Transaction prefixes are evidence-only and
# each transaction is separately checksum-sealed.
readonly -a APPROVED_POST_REVIEW_PATHS=(
  "${APPROVED_FORK_MODIFIED_PATHS[@]}"
  .github/workflows/ci.yml
  .github/workflows/pull-request.yml
  .github/workflows/release.yml
  NOTICE
  compatibility-fixtures/ac07-bidirectional/run-ac07.sh
  compatibility-fixtures/official-10.19.0-generator/gradlew
  compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh
  docs/release/G010-fork-release.md
  evidence/provenance/g011-source-evidence-manifest.json
  tools/g011-evidence-manifest.py
  tools/central-portal.py
  tools/test-central-portal.py
  tools/test-g011-evidence-manifest.py
  tools/__pycache__/g011-evidence-manifest.cpython-314.pyc
  tools/__pycache__/test-g011-evidence-manifest.cpython-314.pyc
  tools/test-g013-independent-review-remediation.py
  tools/test-g013-workflow-trust.py
  tools/test-g014-release-binding.py
  tools/test-ac08-g011-parameterization.py
  tools/test-verify-g010-license.py
  tools/test-verify-baseline.sh
  tools/verify-g010-license.py
  tools/verify-g010-scope.py
  tools/verify-baseline.sh
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
    evidence/g009/ac09/*|\
    evidence/audit/g002-toolchain-final.md|\
    evidence/audit/g003-independent-build-recovery.md|\
    evidence/audit/task-9-preflight.md|\
    compatibility-fixtures/official-10.19.0-generator/*|\
    tools/capture-baseline.py|tools/verify-baseline.sh|\
    tools/verify-release-tag.sh|tools/test-verify-release-tag.sh|\
    tools/verify-g009-ac09-compatibility.py|tools/test-verify-g009-ac09-compatibility.py|\
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

is_post_review_allowed_path() {
  local path="$1"
  local approved_path

  for approved_path in "${APPROVED_POST_REVIEW_PATHS[@]}"; do
    [[ "$path" == "$approved_path" ]] && return 0
  done

  case "$path" in
    .omx/recovery/transactions/G013-independent-review-remediation-*-worker[123]/*|\
    .omx/recovery/transactions/G013-independent-review-trust-boundary-*-worker1/*|\
    .omx/recovery/transactions/G013-reboot-safe-history-remediation-*-worker1/*)
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

verify_recorded_baseline() {
  local baseline="$1"
  local actual

  actual="$(sha256sum "$baseline" | awk '{print $1}')"
  if [[ "$actual" != "$EXPECTED_BASELINE_SHA256" ]]; then
    printf 'immutable baseline manifest digest mismatch: %s\n' "$actual" >&2
    return 1
  fi

  [[ "$(git rev-parse "$EXPECTED_COMMIT:realm/realm-library/src/main/cpp/realm-core")" == "$EXPECTED_BASELINE_CORE" ]]
  [[ "$(git show "$EXPECTED_COMMIT:version.txt")" == "10.19.0" ]]
}

verify_fork_core_gitlinks() {
  local core=realm/realm-library/src/main/cpp/realm-core
  local common_dir core_git_dir

  [[ "$(git rev-parse "HEAD:$core")" == "$EXPECTED_FORK_CORE" ]]
  common_dir="$(git rev-parse --git-common-dir)"
  core_git_dir="$common_dir/modules/$core"
  if [[ ! -d "$core_git_dir" ]]; then
    printf 'Realm Core object store is unavailable: %s\n' "$core_git_dir" >&2
    return 1
  fi

  git --git-dir="$core_git_dir" cat-file -e "$EXPECTED_FORK_CORE^{commit}"
  [[ "$(git --git-dir="$core_git_dir" rev-parse "$EXPECTED_FORK_CORE:external/catch")" == "$EXPECTED_CATCH" ]]
  [[ "$(git --git-dir="$core_git_dir" rev-parse "$EXPECTED_FORK_CORE:src/external/sha-1")" == "$EXPECTED_SHA1" ]]
  [[ "$(git --git-dir="$core_git_dir" rev-parse "$EXPECTED_FORK_CORE:src/external/sha-2")" == "$EXPECTED_SHA2" ]]
}

verify_current_fork_contract() {
  [[ "$(<version.txt)" == "10.19.0-agp9.1" ]]
  grep -qx 'GRADLE_BUILD_TOOLS=9.1.1' dependencies.list
  grep -qx 'gradle=9.6.1' dependencies.list
  grep -qx 'ndkVersion=29.0.14206865' dependencies.list
  grep -qx '    project.ext.minSdkVersion = 21' realm/build.gradle
  grep -qx '    project.ext.compileSdkVersion = 37' realm/build.gradle
  grep -qx "                    abiFilters 'x86_64', 'armeabi-v7a', 'arm64-v8a'" realm/realm-library/build.gradle
}

main() {
  local root path
  local -a invalid_paths=()

  root="$(git rev-parse --show-toplevel)"
  cd "$root"

  [[ "$(git rev-parse "${EXPECTED_TAG}^{commit}")" == "$EXPECTED_COMMIT" ]]
  git merge-base --is-ancestor "$EXPECTED_COMMIT" HEAD
  git merge-base --is-ancestor "$EXPECTED_APPROVED_FORK_ROOT" HEAD
  [[ "$(git remote get-url upstream)" == "https://github.com/realm/realm-java.git" ]]
  [[ "$(git remote get-url origin)" == "https://github.com/Leminity/realm-java.git" ]]

  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    is_post_review_allowed_path "$path" || invalid_paths+=("$path")
  done < <(git diff-tree --no-commit-id --name-only -r "$EXPECTED_APPROVED_FORK_ROOT" HEAD)
  if ((${#invalid_paths[@]})); then
    printf 'unapproved path(s) changed since independent-review root %s:\n' "$EXPECTED_APPROVED_FORK_ROOT" >&2
    printf '  %s\n' "${invalid_paths[@]}" >&2
    exit 1
  fi

  verify_recorded_baseline evidence/provenance/baseline.json
  verify_fork_core_gitlinks
  verify_current_fork_contract
  verify_approved_wrapper_pins
  tools/test-verify-release-tag.sh
  python3 tools/test-g014-release-binding.py

  echo 'baseline provenance verification: PASS'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
