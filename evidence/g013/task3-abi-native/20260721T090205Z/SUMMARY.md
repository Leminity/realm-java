# Task 3 — Native ABI and API37 16 KiB acceptance

## Bound inputs

- Source HEAD: d39316930fd63e379b58bc6296696781099ca4c7
- Core HEAD: d7b52ccbada0283527db36143cfeab18692b4ed0
- Toolchain: Gradle 9.6.1, OpenJDK 17.0.19, Android NDK 29.0.14206865, build-tools 36.0.0
- Device: emulator-5654, AVD realm-api37-ps16k-kvm, SDK 37, PAGE_SIZE=16384
- External actions: none

## Verdicts

- **AC-06 PASS** — fresh Base release AAR contains exactly armeabi-v7a, arm64-v8a, and x86_64; x86 and Sync are absent. All nine inspected PT_LOAD segments use 0x4000 alignment. The representative APK passes zipalign -v -c -P 16 4.
- **AC-07 PASS** — the fork opens official 10.19.0 plain/encrypted generated fixtures, then the official reader reopens fork-modified files. The encrypted wrong key is rejected and migration callbacks remain zero.
- **AC-08 PASS** — on exact API 37 / 16 KiB runtime, six instrumentation tests cover plain/encrypted CRUD, queries, links/lists/null/date/binary/primary keys, commit/rollback, notification/unsubscribe, Realm/managed/results thread confinement, wrong-key rejection, migration N→N+1 exactly once, reopen without migration, and force-stop restart persistence.
- **AC-14 PASS** — execution was direct under WSL2 with no container or page-size compatibility fallback; source, Core, device, artifact and runtime repository provenance are recorded.
- **Build/typecheck/lint PASS** — assembleBaseRelease, release Kotlin/Java compilation and lintBaseRelease succeeded. The scoped debug unit-test task was NO-SOURCE; dedicated native verifier and AC-08 parameterization suites passed 3/3 and 6/6.
- **Regression scan PASS** — binding-owned page-size assumptions and packaged Sync symbols were absent.

## Artifact identities

- Fresh AAR SHA-256: 867340444356ffae837f937bb817c51825581a56f0f5b522a18d7ba23c680397
- Runtime APK SHA-256: 1e8151763f72edfdddc84073f97780bd91df8ef6c3d1c62408c669197d429bcf
- AAB: not produced by the scoped debug runtime fixture; the AAB-specific alignment gate is not applicable.

## Evidence map

- native/report.txt, native/readelf-*.txt — exact ABI and ELF alignment evidence.
- sync-symbol-audit.txt, page-size-source-scan.txt — exclusion/regression scans.
- zipalign-p16.txt, apk-native-inventory.txt — packaged APK evidence.
- device-preflight.txt — exact runtime identity.
- ac07/ — bidirectional official/fork compatibility transaction.
- ac08/20260721T090205Z/ — full API37 16 KiB runtime transaction and its nested verified checksums.
- assemble-base-release.log, typecheck-test-lint-final.log, targeted-script-tests.log — build and validation logs.
- runtime-repository-provenance.txt, runtime-repository-inventory.sha256 — ephemeral local repository provenance.

The failed initial aggregate assembleBase and nonexistent release unit-test task attempts are retained as recovery diagnostics; corrected scoped commands passed. No source files were changed.
