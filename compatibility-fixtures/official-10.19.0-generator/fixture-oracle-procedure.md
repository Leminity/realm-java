# Official 10.19.0 fixture-oracle procedure

## Purpose and isolation

This procedure generates and verifies **baseline** Realm files solely with the official
`io.realm:*:10.19.0` artifacts captured in `../../evidence/oracle/official-10.19.0/maven-artifact-manifest.json`. Run it
in an isolated Android instrumentation project before any fork production-source edit.
The project must resolve `io.realm:realm-gradle-plugin:10.19.0` and the runtime from
Maven Central; record the exact dependency-resolution output with the fixture manifest.

The local upstream checkout was inspected read-only. Relevant upstream evidence is
listed and hashed in `upstream-source-locations.md` and `upstream-source-sha256.txt`:

- `TestRealmConfigurationFactory.java:136-204` builds `RealmConfiguration`, sets the
  directory/name, and applies a caller-provided encryption key.
- `RealmMigration.java:20-71` documents schema-version migration semantics.
- `README.md:221-240` gives the upstream connected instrumentation command
  `cd realm && ./gradlew connectedBaseDebugAndroidTest`.
- `0841_pk_migration.realm` is an existing upstream migration-test asset. It is a
  source example only, **not** a substitute for a new 10.19.0 plain/encrypted oracle.

## Generator contract

1. Pin the generator project's Gradle lock/dependency report to the captured original
   10.19.0 coordinates. Save generator source, lockfiles, device/emulator fingerprint,
   and the SHA-256 of `maven-artifact-manifest.json` with the output.
2. Define one fixed schema and fixed semantic dataset: primary-keyed objects, strings,
   nullable values, dates, binary data, links, lists, and a queryable indexed field.
   Save a canonical JSON golden record sorted by primary key.
3. Set an explicit schema version. Generate `plain.realm` with no encryption and
   `encrypted.realm` using the fixed **test-only 64-byte** vector in
   `fixed-test-key.hex`. This deliberately non-secret reproducibility input is retained
   with the oracle for later fork and wrong-key checks; record its SHA-256 in the
   fixture manifest and never place it in command logs or Gradle arguments.
4. Close each Realm, reopen it with the same official 10.19.0 reader, and export the
   canonical record. The export must exactly equal the golden record. Record fixture
   SHA-256, size, schema version, runtime/device details, and official artifact-manifest
   SHA-256 in `fixture-manifest.json`.
5. Preserve the two original fixture files read-only. Encryption can introduce random
   nonces, so determinism means fixed schema/data/key plus the *first captured* fixture
   hashes and provenance, not byte-for-byte regeneration on later runs.

## Bidirectional reader oracle

For each fixture, always operate on a working copy:

1. Official 10.19.0 reader opens an untouched original and verifies the golden record.
2. The fork reader opens a copy with the same schema/key, performs fixed CRUD, closes,
   reopens, and verifies the expected post-CRUD record without forced migration.
3. Official 10.19.0 reader opens the fork-modified copy and verifies old plus new data.
4. Attempt to open the encrypted copy using a wrong key. Assert failure and re-hash the
   untouched original to prove it was not corrupted.
5. Open same-schema fixtures with a migration callback counter; it must remain zero.
   For a separately generated schema N fixture opened as N+1, assert exactly one defined
   migration and persistence after reopen. Without a migration, record the official
   exception category as baseline behavior.

Never mutate a committed/original oracle fixture in place. The result is not accepted
until the baseline reader pass, fork reader pass, reverse reader pass, wrong-key
integrity check, and fixture-manifest hash are all present.

## Executable generator status

`app/src/androidTest/java/io/realm/fixtureoracle/OfficialFixtureOracleTest.java` is the
executable official-reader generator. It creates, closes, and semantically reopens both
files under the target app's internal files directory; Realm mmap files must not be
created under emulated-storage FUSE. It reads schema and golden-data assets from the
instrumentation context, where the androidTest assets reside.

`run-official-oracle.sh` uses the fixed test key, runs instrumentation, then exports only
the closed plain file, encrypted file, and manifest through debug `run-as` plus `tar`.
It deliberately excludes Realm lock, management, and FIFO files. The host verifier checks
the manifest's official-reader result, the fixed-key fingerprint, and both fixture hashes.

Task-11 execution evidence is under
`../../evidence/oracle/official-10.19.0/fixture-execution/`: the official 10.19.0 baseline
passes on the isolated KVM API-36, 4 KiB oracle. Separate API-37, 16 KiB attempts are
preserved as pre-change official-runtime failure evidence; they do not replace the required
fork API-37, 16 KiB compatibility gate.
