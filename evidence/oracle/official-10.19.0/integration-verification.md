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

## Historical Task-8 fixture preflight: BLOCKED_BEFORE_G002

At the Task-8 preflight snapshot, `compatibility-fixtures/official-10.19.0-generator/`
contained the isolated official 10.19.0-only instrumentation generator,
schema/data assets, bidirectional reader contract, and secret-free key handling.
Static validation had passed, but generated `.realm` files and
`fixture-manifest.json` had not yet been produced.

`fixture-execution/task-8-prerequisite-blocker.md` and `toolchain-lock.json` record
the binding blockers: no API 37 emulator/device, no emulator or Android command-line
tools, only SDK 36.1 available, and offline Gradle dependency resolution failure. The
fixture runtime status at that historical checkpoint was therefore
**BLOCKED_BEFORE_G002**. This historical statement is retained and is superseded by
the terminal Task-11 oracle below; it does not claim a current fixture failure.

## Terminal Task-11 official fixture oracle: PASS

Task 11 completed in commit `934fcb4e0616ff0d7564fd26db9d917fe4467ad5` using the
approved G001-only isolated API 36 / `PAGE_SIZE=4096` internal-files oracle. The
terminal instrumentation run reported `OK (1 test)`, and the official semantic
reader verified both exported files and the manifest. This G001 fixture boundary
does not weaken the later fork-runtime API 37 / `PAGE_SIZE=16384` requirements.

The generated manifest is
`compatibility-fixtures/official-10.19.0-generator/generated/official-10.19.0-oracle/fixture-manifest.json`.
The independently verified hashes are:

- fixed test key SHA-256:
  `fdeab9acf3710362bd2658cdc9a29e8f9c757fcf9811603a8c447cd1d9151108`
- plain fixture SHA-256:
  `46ccf472ba5ae55edb22ae640075df006b377be738ce651abe7507641347b734`
- encrypted fixture SHA-256:
  `792abb7cc4ef3aafe99fd091e0dcd4f1cb713800f60304cc9a4ca6c1d37a23df`
- manifest SHA-256:
  `3aa08c68d046ebb96079f12aa3a6985ef2cffff3827d6c9e18557565875d7344`

The terminal evidence bundle is
`evidence/oracle/official-10.19.0/fixture-execution/task-11-evidence-sha256sum.txt`;
all ten entries verify with `sha256sum --check`. The fixture manifest declares
Realm `10.19.0` and `official_reader_semantic_validation: true`.

## Integration verdict

- **PASS:** official artifact/POM checksum provenance, POM/dynamic graph separation,
  and static public API oracle are available before fork production changes.
- **PASS:** terminal official plain/encrypted fixture generation and semantic-reader
  verification under the G001-only API 36 / 4 KiB boundary, with fixed-key and
  manifest hashes above.
- **PRESERVED GATE:** the later fork-runtime API 37 / 16 KiB compatibility and
  Maven Central release decision still require their own task-10/G002 validation;
  this document does not conflate that gate with the G001 fixture oracle.
