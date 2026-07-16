# G002 exact WSL2 Android toolchain acceptance

**Captured:** 2026-07-16 UTC
**Verdict:** **PASS** — exact G002 toolchain and API37/16 KiB runtime acceptance evidence is present and independently reproduced.

This is the only Task 14 file changed. Production source, Gradle wrappers,
runtime configuration, `.omx`, and goal state were not modified.

## Toolchain checks

Independent commands and results:

```text
java -version       -> openjdk version "17.0.19" 2026-04-21
cmake --version     -> cmake version 3.27.7
./gradlew --version -> Gradle 9.6.1
```

Evidence: `evidence/toolchain/android17-wsl2/environment-diagnostics.txt`,
`java-version.txt`, and `root-gradle-9.6.1-version.txt`.

The official Gradle distribution was locally verified against its published
checksum:

```text
gradle-9.6.1-bin.zip SHA-256:
9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14
```

All eight non-fixture repository wrappers use this exact URL:
`https://services.gradle.org/distributions/gradle-9.6.1-bin.zip`.
Their property files all hash to
`60b4148870401a85004171ac4c42b420805a2ec00dd7787617e66755c9212795`:

```text
examples/gradle/wrapper/gradle-wrapper.properties
gradle-plugin/gradle/wrapper/gradle-wrapper.properties
gradle/wrapper/gradle-wrapper.properties
library-benchmarks/gradle/wrapper/gradle-wrapper.properties
library-build-transformer/gradle/wrapper/gradle-wrapper.properties
realm-annotations/gradle/wrapper/gradle-wrapper.properties
realm-transformer/gradle/wrapper/gradle-wrapper.properties
realm/gradle/wrapper/gradle-wrapper.properties
```

The exact CMake archive is sourced from
`https://cmake.org/files/v3.27/cmake-3.27.7-linux-x86_64.tar.gz` and passes:

```text
a8c92ecb139bcc7a1f92a8108179bd1d021bdb158a5ee759cba6d60010b83ae9
```

Installed SDK evidence independently shows Build Tools `36.0.0`, NDK
`29.0.14206865`, and API 37 platform/system-image packages. The minimal AGP
probe uses `com.android.application` **9.1.1**, `compileSdk = 37`, and
`targetSdk = 37`; its report task completed `BUILD SUCCESSFUL` with
`PROBE_COMPILE_SDK=37` and `PROBE_TARGET_SDK=37`.

## Runtime acceptance

The preserved Docker KVM runtime was queried without changing configuration:

```text
adb -s localhost:5655 get-state                       -> device
adb -s localhost:5655 shell getprop ro.build.version.sdk -> 37
adb -s localhost:5655 shell getconf PAGE_SIZE         -> 16384
docker ps -> realm-api37-kvm Up
```

Runtime evidence is in `evidence/toolchain/android17-wsl2/emulator-final-runtime.txt`
and the completed Task 10 Docker/KVM evidence. The API36/4 KiB oracle
container was stopped separately after Task 11 and is not G002 runtime evidence.

## Version and opt-out guard

The acceptance probe contains no lowered compile/target SDK, NDK, Build Tools,
CMake, Gradle, or AGP version and no legacy opt-out flag. The eight committed
wrapper URLs are all Gradle 9.6.1; the probe reports AGP 9.1.1 with compile and
target 37. The only negative finding is the host user's direct `/dev/kvm`
permission message; Docker KVM evidence satisfies the preserved API37/16 KiB
runtime requirement.

## Source evidence

- `evidence/toolchain/android17-wsl2/agp91-platform-probe.log`
- `evidence/toolchain/android17-wsl2/sdkmanager-list-verified.txt`
- `evidence/toolchain/android17-wsl2/cmake-3.27.7-check.txt`
- `evidence/toolchain/task-12-api37-runtime-audit/official-source-hashes.tsv`
- `evidence/toolchain/task-12-api37-runtime-audit/evidence-sha256sum.txt`
- `evidence/toolchain/android17-wsl2/emulator-final-runtime.txt`
