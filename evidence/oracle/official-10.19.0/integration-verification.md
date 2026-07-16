# G001 Official 10.19.0 Oracle Integration

This is an integration verdict over the captured worker-3 oracle. It does not copy or
replace any captured artifact, POM, API dump, fixture procedure, or fixture generator.

## Verified immutable inputs

From the repository root, the prescribed path-relative checks passed:

```sh
sha256sum --check evidence/oracle/official-10.19.0/checksums/evidence-sha256sum.txt
sha256sum --check evidence/oracle/official-10.19.0/fixture-execution/task-8-evidence-sha256sum.txt
```

The first checks the Maven manifest, public-class inventory, `javap` API dump, fixture
procedure, and upstream source-location digest. The second binds the task-8 static
fixture evidence, blocked Gradle/runtime preflights, and toolchain lock to their
recorded SHA-256 values. These commands must be run from the repository root because
their manifests use root-relative paths.

## Official Maven/API graph baseline

`maven-artifact-manifest.json` pins six downloaded `io.realm:*:10.19.0` components,
their Maven Central SHA-1 values, local SHA-256 values, artifact/POM URLs, and exact
POMs under `poms/`:

1. `realm-gradle-plugin`
2. `realm-transformer`
3. `realm-annotations`
4. `realm-annotations-processor`
5. `realm-android-library`
6. `realm-android-kotlin-extensions`

The preserved POMs are the normalized POM-edge source of truth. In particular, they
show plugin → transformer, transformer → annotations, processor → annotations, and
base-library → annotations. Kotlin extensions intentionally have no base-library POM
edge; the plugin provides that runtime edge dynamically.

The dynamic injection graph is kept separate, as required by the test specification.
Upstream `gradle-plugin/src/main/kotlin/io/realm/gradle/Realm.kt:43-70,131-161` injects
`realm-annotations`, `realm-annotations-processor` (KAPT or Java annotation-processor
paths), `realm-android-library`, and the optional Kotlin extensions artifact. Its
`syncEnabled` branch can select `-object-server`; it is baseline evidence only and
must be removed from the fork's supported/release graph by a later failure-ledger
backed change. This report does not treat POM edges as dynamic edges or vice versa.

`api/public-class-inventory.tsv`, `api/public-api-javap.txt`, and
`api/javap-jobs.tsv` are the official public API oracle. `api/javap-failures.txt` is
retained so any absent/decompilation-limited class is visible rather than silently
accepted.

## Fixture oracle status: BLOCKED, not PASS

`compatibility-fixtures/official-10.19.0-generator/` contains the isolated official
10.19.0-only instrumentation generator, schema/data assets, bidirectional reader
contract, and secret-free key handling. Static validation passed, but there are no
generated `.realm` files or `fixture-manifest.json`.

`fixture-execution/task-8-prerequisite-blocker.md` and `toolchain-lock.json` record
the binding blockers: no API 37 emulator/device, no emulator or Android command-line
tools, only SDK 36.1 available, and offline Gradle dependency resolution failure. The
fixture runtime status is therefore **BLOCKED_BEFORE_G002**. No plain/encrypted reader
compatibility, encryption-key digest, or bidirectional file-compatibility PASS is
claimed by this integration.

## Integration verdict

- **PASS:** official artifact/POM checksum provenance, POM/dynamic graph separation,
  and static public API oracle are available before fork production changes.
- **BLOCKED:** executable plain/encrypted fixture generation and reader verification;
  task 10/G002 must run the generator on the binding API 37 runtime before any
  compatibility PASS or Maven Central release decision.
