# AC-08 API 37 / 16 KiB Acceptance Evidence

## Runs

- Task 7 clean run: `evidence/ac08-api37-ps16k/ac08-final-clean-restart-20260717T005300Z`
- Task 5 adversarial repeat: `evidence/ac08-api37-ps16k/ac08-task5-adversarial-repeat-20260717T005600Z`
- Device: `emulator-5654`, SDK 37, `PAGE_SIZE=16384`; both runs used `/tmp/realm-g009-device.lock`.
- Clean-run restart proof: PID A `9181` matched live, became absent after force-stop; PID B `9233` differed and reopened both plain/encrypted sentinels.
- Official thread categories: Realm, managed object, and RealmResults all `java.lang.IllegalStateException`.
- Official no-migration category: `io.realm.exceptions.RealmMigrationNeededException`.
- Immutable encrypted fixture SHA-256: `792abb7cc4ef3aafe99fd091e0dcd4f1cb713800f60304cc9a4ca6c1d37a23df`.
- Fork runtime: `OK (6 tests)`; both raw run manifests and checksums passed.

## Durable archive

- Archive: `.omx/recovery/transactions/G009-ac08-final-evidence-20260717T010049Z.tar.gz`
- Archive SHA-256: `8c12980590fc4faa7db69607f1cf74a6cddd1a8f20b2d9446eef63e3dbc86133`
- Raw manifest SHA-256: `a0f5b9ed124f441dc0a89db61546b41c0ad202e8cdd7d6b219345b3ab55fd2b4`
- Extraction and `sha256sum -c` verification: PASS for all raw files.

## Audit

- Harness commit: `cd84cabf3653f2302e2b3f2764694239c50e6bd1`.
- Commit paths are limited to the AC-08 fixture README, runner, manifest, and tests; no production or `.omx/ultragoal` paths were changed.
- PASS commands: `bash -n compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh`; offline official/fork builds; full runner `result.txt=AC08=PASS`.
- No raw logcat, APK, generated build output, device action, push, or Maven Central action is included in the tracked report.
