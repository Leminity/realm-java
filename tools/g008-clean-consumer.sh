#!/usr/bin/env bash
# Resolve all six fork artifacts from a local staging repository without any
# Maven-local fallback. Google and Central remain available only for external
# dependencies; the fork group is exclusively routed to the supplied staging.
set -euo pipefail

usage() {
  echo "usage: $0 --repository <local-maven-repository>" >&2
  exit 2
}

[[ $# -eq 2 && $1 == "--repository" ]] || usage
repository="$(cd "$2" && pwd)"
root="$(git rev-parse --show-toplevel)"
consumer="$(mktemp -d)"
gradle_user_home="$(mktemp -d)"
trap 'rm -rf "$consumer" "$gradle_user_home"' EXIT

cat > "$consumer/settings.gradle" <<'SETTINGS'
dependencyResolutionManagement {
    repositories {
        maven {
            url = uri(System.getenv('G008_STAGING_REPOSITORY'))
            content { includeGroup('io.github.leminity.realm') }
        }
        google { content { excludeGroup('io.github.leminity.realm') } }
        mavenCentral { content { excludeGroup('io.github.leminity.realm') } }
    }
}
rootProject.name = 'g008-clean-consumer'
SETTINGS

cat > "$consumer/build.gradle" <<'BUILD'
plugins { id 'java' }

configurations { g008 }
dependencies {
    g008 'io.github.leminity.realm:realm-gradle-plugin:10.19.0-agp9.1'
    g008 'io.github.leminity.realm:realm-transformer:10.19.0-agp9.1'
    g008 'io.github.leminity.realm:realm-annotations:10.19.0-agp9.1'
    g008 'io.github.leminity.realm:realm-annotations-processor:10.19.0-agp9.1'
    g008 'io.github.leminity.realm:realm-android-library:10.19.0-agp9.1'
    g008 'io.github.leminity.realm:realm-android-kotlin-extensions:10.19.0-agp9.1'
}

tasks.register('verifyG008Consumer') {
    doLast {
        def resolved = configurations.g008.resolvedConfiguration.resolvedArtifacts.collect {
            "${it.moduleVersion.id.group}:${it.name}:${it.moduleVersion.id.version}"
        }.findAll { it.startsWith('io.github.leminity.realm:') }.toSet()
        def expected = [
            'realm-gradle-plugin', 'realm-transformer', 'realm-annotations',
            'realm-annotations-processor', 'realm-android-library',
            'realm-android-kotlin-extensions'
        ].collect { "io.github.leminity.realm:${it}:10.19.0-agp9.1" }.toSet()
        if (resolved != expected) {
            throw new GradleException("G008 consumer resolved ${resolved}; expected ${expected}")
        }
        println 'G008 clean local consumer: PASS'
    }
}
BUILD

# A fresh user home proves resolution is not satisfied by a stale cache. The
# generated settings intentionally omit mavenLocal, and route the fork group
# only to the caller-provided repository.
G008_STAGING_REPOSITORY="$repository" GRADLE_USER_HOME="$gradle_user_home" \
  "$root/gradlew" -g "$gradle_user_home" -p "$consumer" --no-daemon verifyG008Consumer
