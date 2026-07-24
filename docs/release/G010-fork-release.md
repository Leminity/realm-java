# G010 fork and release contract

This document describes the reproducible, **unofficial Leminity maintenance fork** of Realm
Java. It is a local-consumer and compatibility contract, not a promise of upstream or MongoDB
support.

## Provenance and coordinates

- Upstream baseline: tag `v10.19.0`.
- Release-candidate tag input: `v10.19.0-agp9.2`.
- Immutable predecessor: tag `v10.19.0-agp9.1`.
- Historical integration milestone: `0e8bddf0a46827a7336a6a13406df8e35834db25`.
- Current canonical Realm Core source provenance: `a5b7ed7bb8f0db4d362c7e45b2f38358a4aeab47`; historical behavior backport: `d7b52ccb`.
- Version: `10.19.0-agp9.2` (`version.txt`).
- Maven coordinates use group `io.github.leminity.realm`; the six fork artifacts are
  `realm-gradle-plugin`, `realm-transformer`, `realm-annotations`,
  `realm-annotations-processor`, `realm-android-library`, and
  `realm-android-kotlin-extensions`.

## R8 consumer metadata

Realm reflects over classes annotated with `@RealmModule`. In the predecessor release, the AAR
consumer metadata kept those classes but did not retain their constructors, so R8 could remove
the constructor needed by Realm at runtime. `10.19.0-agp9.2` packages the exact
`@RealmModule` constructor keep rule in the Realm AAR. After upgrading to `.2`, consumers should
remove any equivalent application-local workaround; a broad package keep is neither needed nor
part of this release.

## Supported boundary

This release contract covers the base local Realm database on Android. Sync, ObjectServer,
server-backed sessions, and related services are unsupported and excluded. Do not infer Sync
support from upstream documentation or from dependencies present in historical projects.

The native ABI set is exactly `arm64-v8a`, `armeabi-v7a`, and `x86_64`; `x86` is not released.

## Reproducible WSL2 toolchain

Use WSL2 with JDK 17, Gradle 9.6.1, Android Gradle Plugin 9.1.1, Android SDK/API 37,
`minSdk=21`, NDK `29.0.14206865`, and CMake `3.27.7`. The pinned values are recorded in
`dependencies.list`, `realm/realm/build.gradle`, and the Gradle wrapper properties.

```bash
export ANDROID_SDK_ROOT=/home/$USER/Android/Sdk
export JAVA_HOME=/path/to/jdk-17
./tools/verify-toolchain.sh --sdk-root "$ANDROID_SDK_ROOT" \
  --evidence-dir evidence/toolchain/g010-wsl2
./gradlew --version
```

Build the base variant without publishing:

```bash
(cd realm && ./gradlew --no-daemon --offline assembleBase)
```

## Local signed stage and clean consumer

Point consumers at an existing local signed Maven-layout stage. The clean-consumer script uses
a fresh Gradle user home, excludes `mavenLocal`, and routes the fork group only to the supplied
directory:

```bash
export G008_STAGING_REPOSITORY=/absolute/path/to/g008-root-final-stage-run1/repository
G008_STAGING_REPOSITORY="$G008_STAGING_REPOSITORY" \
  ./tools/g008-clean-consumer.sh --repository "$G008_STAGING_REPOSITORY"
```

For the checked API 37 / 16 KiB runtime fixture, use the same local stage and the exclusive
device lock managed by the runner:

```bash
AC08_RUN_ID="g010-$(date -u +%Y%m%dT%H%M%SZ)" \
  ./compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh
```

The fixture's official Realm inputs are immutable artifacts from
`compatibility-fixtures/official-10.19.0-generator/generated/official-10.19.0-oracle/` and
must be copied to working locations, never regenerated or modified in place.

## Credentials and revision rule

If a release operator later performs an authorized Central publication outside this local
verification workflow, credentials may be supplied by variable names only:
`MAVENCENTRAL_USERNAME`, `MAVENCENTRAL_PASSWORD`, `SIGNING_KEY`, and `SIGNING_PASSWORD`.
Never commit values, tokens, private keys, or generated signing material. The commands above
are offline/local-only and perform no upload, push, or publication.

Every revision must record the exact source and Core SHAs, preserve the three-ABI boundary,
rerun the clean consumer and API 37 / 16 KiB fixture, and retain checksummed evidence. A
revision that changes those inputs or boundaries requires a new documented revision rather
than silently reusing this contract.

The `.2` tag may be created only after its exact source commit has passed the release gates and
been sealed as the tag input. Once created, it is immutable. The existing
`v10.19.0-agp9.1` tag and published artifacts must not be moved or replaced.

## Archival upstream instructions

The older upstream JDK 8, Android Studio 4.1.1, API 29, NDK 21, CMake 3.18.4, S3 Core cache,
Sonatype OSSRH, and historical ObjectServer instructions in the upstream README are archival
context only. They are not release instructions for this fork and must not be used to publish,
upload, or claim support for the excluded services.
