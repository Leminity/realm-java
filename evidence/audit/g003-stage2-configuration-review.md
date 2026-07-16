# G003 Stage 2 independent-build configuration review

**Status:** baseline reproduced; Stage 2 is **not yet passed**.
**Scope:** G003 prerequisite recovery only. This review does not perform the
G004 `BaseExtension`/Transformer migration and does not change production
Realm Java/Kotlin/C/C++ sources.

## Fixed constraints

The follow-up implementation and its evidence must preserve these values:

- AGP `9.1.1`, Gradle `9.6.1`, JDK `17`, SDK/compile-target `37`, minSdk `21`,
  and NDK `29.0.14206865`.
- No `android.newDsl=false`, `android.builtInKotlin=false`, or equivalent
  legacy opt-out.
- Supported order is `realm-annotations -> realm-transformer ->
  library-build-transformer -> realm base/processor/kotlin-extensions ->
  realm-gradle-plugin`.
- Examples, benchmarks, ObjectServer, and Sync are outside the supported
  release graph and must not be published.

These constraints are taken from Stage 2 of
`.omx/plans/realm-java-android17-agp9-mavencentral.md` and the independent
build order in its companion test specification. The leader-owned G003 ledger
entry remains the audit authority; this file does not modify goal or ledger
state.

## Reproduced failure

**Failure ID:** `G003-F01-jcenter-removed-in-gradle-9`
**Environment:** OpenJDK `17.0.19`; Gradle wrapper `9.6.1`.

Each command was run from its independent build directory with
`./gradlew --no-daemon --console=plain help`, in the required order. Every
command failed during configuration, before dependency resolution or task
execution:

| Build | Build file / line | Result |
| --- | --- | --- |
| `realm-annotations` | `realm-annotations/build.gradle:6` | `Could not find method jcenter()` |
| `realm-transformer` | `realm-transformer/build.gradle:7` | `Could not find method jcenter()` |
| `library-build-transformer` | `library-build-transformer/build.gradle:8` | `Could not find method jcenter()` |
| `realm` | `realm/build.gradle:10` | `Could not find method jcenter()` |
| `gradle-plugin` | `gradle-plugin/build.gradle:10` | `Could not find method jcenter()` |

The exact first-failure logs were captured during this review. The common
error is a Gradle 9 configuration failure, so it is not evidence of a missing
artifact or a permitted reason to lower Gradle/AGP or enable a legacy opt-out.

## Code-quality and boundary findings

### Confirmed from the checkout

1. `dependencies.list:18-27` still pins AGP `7.4.0`, Kotlin `1.6.21`, Gradle
   `7.5`, NDK `23.1.7779620`, the old build-info plugin, and old Nexus plugin.
   These conflict with the fixed G003 toolchain; pure-JVM Kotlin must move to
   the approved KGP `2.2.10` only as part of a verified compatibility change.
2. The first configuration blocker is `jcenter()` in all five supported
   independent build scripts. It must be addressed first, narrowly, and only
   together with the repositories needed to resolve the verified replacement
   coordinates.
3. `gradle-plugin/build.gradle:1-2,76-79` imports/uses
   `org.gradle.api.internal.classpath.ModuleRegistry` and
   `org.gradle.api.internal.project.ProjectInternal`. This is a separate
   post-repository G003 blocker; replace it with public Gradle/TestKit
   behavior, not reflection or another internal API.
4. The root graph retains the necessary build ordering
   (`build.gradle:74-112,174-207`) but the generic `assemble` path still
   depends on examples (`build.gradle:271-275`). A release-only task graph
   assertion is required; the current separation of task declarations alone
   is not proof that examples/ObjectServer/Sync are not configured or run.
5. `build.gradle:311-315,349-353` still deletes the upstream
   `~/.m2/repository/io/realm` path. The G003 fork-group replacement must be
   tested as a narrow root-clean change.
6. `mavencentral-publish.gradle` still applies the old Nexus publishing
   plugin and old OSSRH endpoints. Stage 2 permits removing/replacing this
   only when the corresponding configuration/resolution failure is reproduced;
   no publication task was invoked by this review.

### Explicitly deferred

- `realm-transformer`'s `BaseExtension`/`AndroidArtifacts` migration is G004,
  not a shortcut for this prerequisite stage.
- Android DSL, `kotlin-android`, `kotlin-kapt`, native header wiring, and
  production source changes require a direct failure and their own ledger/test
  link before modification.
- No Sync/ObjectServer/examples/benchmarks configuration or publication was
  attempted as a substitute for the supported chain.

## Required implementation evidence after `G003-F01`

The next change must link its diff to `G003-F01`, the new command log, and the
leader-owned G003 ledger entry. It is not sufficient to make the first
`jcenter()` error disappear. The following checks must pass in order:

1. `help` for the five independent build roots above, then the realm
   base/processor/Kotlin-extension targeted configuration tasks.
2. Targeted unit tests and publication metadata generation for every supported
   artifact in the stated build order.
3. A Gradle task-graph assertion proving the release path neither configures
   nor executes examples, benchmarks, ObjectServer, or Sync.
4. A clean-resolution/network assertion: fork-owned coordinates resolve from
   the intended local/approved repositories and no excluded graph triggers
   retired Realm/S3/old-OSSRH operations.
5. Static tests that reject `org.gradle.internal.*`, Gradle API internals,
   legacy AGP opt-outs, and forbidden release publications. The broader
   `BaseExtension`/`AndroidArtifacts` bytecode ban remains G004 verification.

## Verification performed for this review

- **PASS:** all eight wrapper property files remain pinned to Gradle `9.6.1`
  with the same distribution SHA-256.
- **PASS:** `java -version` reports JDK `17.0.19`; root `./gradlew --version`
  reports Gradle `9.6.1`.
- **PASS:** the five-command ordered baseline deterministically reproduces
  `G003-F01` before resolution/task execution.
- **PASS:** this documentation-only diff introduces no production-source or
  Gradle-script change; a production-diff ledger update is therefore not
  applicable.
- **NOT RUN (blocked by G003-F01):** targeted tests, metadata generation, and
  release task-graph assertions. Running them now would repeat the same
  configuration failure and cannot demonstrate Stage 2 recovery.
