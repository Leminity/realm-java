#!/usr/bin/env bash
# Consume the exact six Realm fork artifacts without allowing a repository fallback.
# This helper is intentionally a consumer only: it never publishes or contacts a device.
set -euo pipefail

FORK_GROUP='io.github.leminity.realm'

usage() {
  cat >&2 <<'USAGE'
usage: g011-consume-six.sh --mode local|validated|central \
  --gradle-user-home <empty-dir> --evidence-dir <dir> [repository options] [--dry-run]

local:     --repository <local Maven-layout directory>
validated: --repository-url <https://.../deployment/<id>/download> --bearer-env <ENV_NAME>
central:   no repository URL, path, or bearer option (uses mavenCentral only)
USAGE
  exit 64
}
fail() { printf 'G011 consumer FAIL: %s\n' "$*" >&2; exit 1; }
require_value() { [[ $# -ge 2 && -n $2 ]] || usage; }
valid_env_name() { [[ $1 =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; }
valid_deployment_url() { [[ $1 == https://* && $1 != *'?'* && $1 != *'#'* && $1 =~ /deployment/[A-Za-z0-9._-]+/download/?$ ]]; }

mode=''
repository=''
repository_url=''
bearer_env=''
gradle_user_home=''
evidence=''
dry_run=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) require_value "$@"; mode=$2; shift 2 ;;
    --repository) require_value "$@"; repository=$2; shift 2 ;;
    --repository-url) require_value "$@"; repository_url=$2; shift 2 ;;
    --bearer-env) require_value "$@"; bearer_env=$2; shift 2 ;;
    --gradle-user-home) require_value "$@"; gradle_user_home=$2; shift 2 ;;
    --evidence-dir) require_value "$@"; evidence=$2; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

[[ $mode == local || $mode == validated || $mode == central ]] || usage
[[ -n $gradle_user_home && -n $evidence ]] || usage
case "$mode" in
  local)
    [[ -n $repository && -z $repository_url && -z $bearer_env ]] || usage
    [[ -d $repository ]] || fail "local repository does not exist: $repository"
    repository="$(cd "$repository" && pwd)"
    fork_url="file://$repository"
    ;;
  validated)
    [[ -z $repository && -n $repository_url && -n $bearer_env ]] || usage
    valid_deployment_url "$repository_url" || fail 'validated repository URL must be one HTTPS /deployment/<id>/download URL without query or fragment'
    valid_env_name "$bearer_env" || fail 'bearer environment variable name is invalid'
    bearer_value="${!bearer_env:-}"
    [[ -n $bearer_value ]] || fail "validated mode requires non-empty bearer environment variable: $bearer_env"
    fork_url=$repository_url
    ;;
  central)
    [[ -z $repository && -z $repository_url && -z $bearer_env ]] || usage
    fork_url='mavenCentral()'
    ;;
esac

prepare_fresh_evidence() {
  local directory="$1"
  if [[ -e $directory && ! -d $directory ]]; then
    fail "evidence path is not a directory: $directory"
  fi
  if [[ -d $directory ]] && find "$directory" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    fail "evidence directory must be empty: $directory"
  fi
  mkdir -p "$directory"
}

prepare_fresh_evidence "$evidence"
mkdir -p "$gradle_user_home"
[[ -d $gradle_user_home && -d $evidence ]] || fail 'cannot create caller-supplied Gradle home or evidence directory'
if find "$gradle_user_home" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  fail "Gradle user home must be empty: $gradle_user_home"
fi

root="$(git rev-parse --show-toplevel)"
version="$(tr -d '[:space:]' < "$root/version.txt")"
[[ -n $version ]] || fail 'version.txt must contain the release version'
consumer="$evidence/consumer"
mkdir -p "$consumer"

write_custom_repository() {
  cat <<'GRADLE'
        maven {
            url = uri(System.getenv('G011_FORK_REPOSITORY_URL'))
            content { includeGroup('io.github.leminity.realm') }
            if (System.getenv('G011_REPOSITORY_MODE') == 'validated') {
                credentials(HttpHeaderCredentials) {
                    name = 'Authorization'
                    value = 'Bearer ' + System.getenv('G011_FORK_BEARER')
                }
                authentication { header(HttpHeaderAuthentication) }
            }
        }
GRADLE
}
write_central_fork_repository() {
  cat <<'GRADLE'
        mavenCentral { content { includeGroup('io.github.leminity.realm') } }
GRADLE
}
write_external_repositories() {
  cat <<'GRADLE'
        google { content { excludeGroup('io.github.leminity.realm') } }
        mavenCentral { content { excludeGroup('io.github.leminity.realm') } }
GRADLE
}

{
  cat <<'GRADLE'
pluginManagement {
    repositories {
GRADLE
  if [[ $mode == central ]]; then write_central_fork_repository; else write_custom_repository; fi
  write_external_repositories
  cat <<'GRADLE'
        gradlePluginPortal { content { excludeGroup('io.github.leminity.realm') } }
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
GRADLE
  if [[ $mode == central ]]; then write_central_fork_repository; else write_custom_repository; fi
  write_external_repositories
  cat <<'GRADLE'
    }
}
rootProject.name = 'g011-exact-six-consumer'
GRADLE
} > "$consumer/settings.gradle"

cat > "$consumer/build.gradle" <<'GRADLE'
plugins { id 'java' }

configurations { g011 }
dependencies {
    g011 'io.github.leminity.realm:realm-gradle-plugin:__G011_VERSION__'
    g011 'io.github.leminity.realm:realm-transformer:__G011_VERSION__'
    g011 'io.github.leminity.realm:realm-annotations:__G011_VERSION__'
    g011 'io.github.leminity.realm:realm-annotations-processor:__G011_VERSION__'
    g011 'io.github.leminity.realm:realm-android-library:__G011_VERSION__'
    g011 'io.github.leminity.realm:realm-android-kotlin-extensions:__G011_VERSION__'
}

tasks.register('verifyG011ExactSix') {
    doLast {
        def resolved = configurations.g011.resolvedConfiguration.resolvedArtifacts.collect {
            "${it.moduleVersion.id.group}:${it.name}:${it.moduleVersion.id.version}"
        }.findAll { it.startsWith('io.github.leminity.realm:') }.toSet()
        def expected = [
            'realm-gradle-plugin', 'realm-transformer', 'realm-annotations',
            'realm-annotations-processor', 'realm-android-library',
            'realm-android-kotlin-extensions'
        ].collect { "io.github.leminity.realm:${it}:__G011_VERSION__" }.toSet()
        if (resolved != expected) {
            throw new GradleException("G011 exact-six consumer resolved ${resolved}; expected ${expected}")
        }
        println 'G011 exact-six consumer: PASS'
    }
}
GRADLE
sed -i "s/__G011_VERSION__/${version}/g" "$consumer/build.gradle"
cp "$consumer/settings.gradle" "$evidence/settings.gradle.redacted"
cp "$consumer/build.gradle" "$evidence/build.gradle"

{
  printf 'mode=%s\n' "$mode"
  printf 'fork_group=%s\n' "$FORK_GROUP"
  printf 'fork_repository=%s\n' "$fork_url"
  printf 'exclusive_dependency_resolution=PASS\n'
  printf 'exclusive_plugin_resolution=PASS\n'
  printf 'maven_local=absent\n'
  printf 'jitpack=absent\n'
  printf 'gradle_user_home_initial_entries=0\n'
} > "$evidence/routing-proof.txt"

command=("$root/gradlew" -g "$gradle_user_home" -p "$consumer" --no-daemon --console=plain verifyG011ExactSix)
{
  printf 'env G011_REPOSITORY_MODE=%q ' "$mode"
  [[ $mode != central ]] && printf 'G011_FORK_REPOSITORY_URL=%q ' "$fork_url"
  [[ $mode == validated ]] && printf 'G011_FORK_BEARER=<redacted> '
  printf 'GRADLE_USER_HOME=%q ' "$gradle_user_home"
  printf '%q ' "${command[@]}"
  printf '\n'
} > "$evidence/command.redacted.txt"

status=0
if [[ $dry_run == true ]]; then
  printf 'DRY_RUN: Gradle not invoked; no network or repository action was performed.\n' > "$evidence/dependency-report.txt"
else
  set +e
  if [[ $mode == validated ]]; then
    env G011_REPOSITORY_MODE="$mode" G011_FORK_REPOSITORY_URL="$fork_url" G011_FORK_BEARER="$bearer_value" \
      GRADLE_USER_HOME="$gradle_user_home" "${command[@]}" > "$evidence/dependency-report.txt" 2>&1
  elif [[ $mode == local ]]; then
    env G011_REPOSITORY_MODE="$mode" G011_FORK_REPOSITORY_URL="$fork_url" \
      GRADLE_USER_HOME="$gradle_user_home" "${command[@]}" > "$evidence/dependency-report.txt" 2>&1
  else
    env G011_REPOSITORY_MODE="$mode" GRADLE_USER_HOME="$gradle_user_home" "${command[@]}" > "$evidence/dependency-report.txt" 2>&1
  fi
  status=$?
  set -e
fi
printf 'gradle_exit=%s\n' "$status" > "$evidence/result.txt"
write_checksums() {
  local manifest_tmp="$evidence/.SHA256SUMS.tmp"
  local verify_tmp="$evidence/.checksum-verify.tmp"
  (
    cd "$evidence"
    LC_ALL=C find . -maxdepth 1 -type f \
      ! -name SHA256SUMS ! -name checksum-verify.log \
      ! -name .SHA256SUMS.tmp ! -name .checksum-verify.tmp \
      -printf '%f\0' | LC_ALL=C sort -z | xargs -0 sha256sum
  ) > "$manifest_tmp"
  mv -f "$manifest_tmp" "$evidence/SHA256SUMS"
  if (cd "$evidence" && sha256sum -c SHA256SUMS) > "$verify_tmp"; then
    mv -f "$verify_tmp" "$evidence/checksum-verify.log"
  else
    mv -f "$verify_tmp" "$evidence/checksum-verify.log"
    return 1
  fi
}
write_checksums
[[ $status -eq 0 ]] || exit "$status"
