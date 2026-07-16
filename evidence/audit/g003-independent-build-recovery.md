# G003 Independent Build Recovery — Lane C Verification Evidence

## Scope

- **Failure ID:** `F-G003-001`
- **Task boundary:** Stage 2 only. This evidence covers the release-critical
  independent-build verification contract; it does not migrate the Realm
  Transformer (`G004`) or change production Realm Java/Kotlin/C/C++ sources.
- **Supported order:** `realm-annotations` → `realm-transformer` →
  `library-build-transformer` → Realm base/annotation processor/Kotlin
  extensions → `realm-gradle-plugin`.

## Reproduced baseline failure

On the exact installed wrapper/JDK pair, every release-critical `help` command
failed before dependency resolution because Gradle 9.6.1 no longer provides
`jcenter()`:

```text
./gradlew help --no-daemon --stacktrace
./realm-annotations/gradlew help --no-daemon --stacktrace
./realm-transformer/gradlew help --no-daemon --stacktrace
./library-build-transformer/gradlew help --no-daemon --stacktrace
./realm/gradlew help --no-daemon --stacktrace
./gradle-plugin/gradlew help --no-daemon --stacktrace
```

Each command exited `1` with `Could not find method jcenter()`; the initial
locations are root `build.gradle:6`, annotations `:6`, transformer `:7`,
library build transformer `:8`, Realm `:10`, and Gradle plugin `:10`.

## Regression contract

`tools/verify-g003-independent-builds.sh` requires:

- all eight wrappers pinned to Gradle 9.6.1 and its official SHA-256;
- AGP 9.1.1, KGP 2.2.10, SDK/target 37, minSdk 21, Build Tools 36.0.0,
  NDK 29.0.14206865, and JDK 17;
- no `jcenter()`, legacy AGP opt-out, `kotlin-android`, or main Gradle-plugin
  `org.gradle.internal` use on the supported path;
- the ordered isolated Gradle/Maven matrix, targeted metadata tasks, and the
  mandatory `installRealmJava --dry-run` root graph assertion;
- rejection of forbidden hosts and actual Gradle task lines for legacy
  Sonatype/S3 and examples, benchmarks, ObjectServer, or Sync work;
- exactly the six public POM artifactIds, with no ObjectServer/Sync/internal
  build-transformer publication metadata.

The matching regression test has an explicit allowed lexical `ObjectServer`
line and rejects only actual task lines, preventing a false positive from the
retained unsupported source history.

## Fresh command evidence

| Command | Result |
| --- | --- |
| `tools/test-verify-g003-independent-builds.sh` | PASS |
| `bash -n tools/verify-g003-independent-builds.sh tools/test-verify-g003-independent-builds.sh tools/verify-baseline.sh tools/test-verify-baseline.sh` | PASS |
| `tools/verify-toolchain.sh --sdk-root "$HOME/Android/Sdk" --evidence-dir /tmp/g003-toolchain-verification` | PASS (SDK XML warnings only) |
| `tools/verify-g003-independent-builds.sh` before Lane A/B integration | Expected FAIL: `GRADLE_BUILD_TOOLS=7.4.0`, proving the exact-toolchain gate is red before the repair |

`tools/test-verify-baseline.sh` is not runnable in this OMX worker worktree:
after initializing its nested Realm Core submodules, `capture-baseline.py`
stops at `git symbolic-ref --short HEAD` because team worktrees are detached.
This occurs before the allowlist assertions and is an execution-environment
gap, not a regression assertion failure. The phase-aware path predicate was
separately exercised for the exact G003 verifier/evidence paths and rejects
adjacent unapproved paths.

## Integration handoff

After the implementation commit is integrated, run:

```text
tools/verify-g003-independent-builds.sh --run --evidence-dir build/g003-independent-builds
```

A passing result is required before G003 closes. Do not treat the current
pre-integration static failure as a Stage 2 pass.
