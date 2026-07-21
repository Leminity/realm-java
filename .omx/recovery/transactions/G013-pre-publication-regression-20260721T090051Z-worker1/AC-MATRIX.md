# G013 exact integrated source acceptance command matrix

Source under test: `d39316930fd63e379b58bc6296696781099ca4c7` with Realm Core gitlink/worktree `d7b52ccbada0283527db36143cfeab18692b4ed0`.
All commands are local/reversible. Upload, drop, tag, GitHub Release, Central stage, and publish are forbidden in this worker run.

| AC | Local command/evidence owner | Task-1 status |
|---|---|---|
| AC-01 | `tools/verify-toolchain.sh --sdk-root /home/leminity/Android/Sdk --evidence-dir <tx>/artifacts/toolchain`; wrapper checks in `tools/verify-toolchain.sh` | PASS: 8 wrappers / Gradle 9.6.1 SHA-256 |
| AC-02 | same toolchain verifier; `tools/verify-g003-independent-builds.sh --run`; TestKit/plugin gates; dependency/fixture pin scans | PASS exact JDK17/SDK37/NDK29 availability; build replay assigned Task 2/4 |
| AC-03 | `tools/verify-g004-transformer-public-api.sh --run`; internal API scans in G010 scope/publication gates | mapped to Task 4 |
| AC-04 | `./gradle-plugin/gradlew --project-dir gradle-plugin --no-daemon --console=plain cleanTest test`; G003/G004 matrix | mapped to Task 4 |
| AC-05 | `python3 tools/verify-g010-scope.py --write-report <report>` plus supported graph/log denylist scan | mapped to Task 4/5 |
| AC-06 | `tools/g011-verify-native-elf.sh --bundle <bundle> --evidence-dir <dir> --ndk-root /home/leminity/Android/Sdk/ndk/29.0.14206865`; final APK `zipalign -P 16`; AC08 JNI load | mapped to native/runtime lane; target availability PASS |
| AC-07 | `compatibility-fixtures/ac07-bidirectional/run-ac07.sh` with the fresh local G008 repository; oracle checksum/provenance verifier | mapped to runtime lane |
| AC-08 | `compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh --mode local --repository <stage> --sdk-root /home/leminity/Android/Sdk --serial emulator-5654 --expected-avd realm-api37-ps16k-kvm --evidence-dir <dir> --run-id <id>` | API37/16384 identity PASS; execution mapped to runtime lane |
| AC-09 | fresh official resolver then `python3 tools/verify-g009-ac09-compatibility.py --official-cache <cache> --fork-repository <stage> --output-dir <dir>` and its unit test | mapped to Task 4 |
| AC-10 | ephemeral local key + `tools/publish_release.sh --signed-bundle`; `python3 tools/g008-publication.py --repository <stage> --require-signatures --manifest <manifest> --bundle <bundle> --plugin-source ...`; `tools/g011-consume-six.sh --mode local ...` | mapped to Task 4 |
| AC-11 | same G008 verifier/bundle plus `python3 tools/verify-g010-license.py --repository <stage> --report <report>` and unit test | mapped to Task 4 |
| AC-12 | `python3 tools/test-central-portal.py`, `python3 tools/test-g013-direct-validation-workflow.py`, privacy/static scans; protected environment/Central actions remain external-gate pending | local contract mapped to Task 5/6; external mutation forbidden |
| AC-13 | exact validated deployment and public Central clean consumers with identical AC08 suite | EXTERNAL-GATE PENDING; no deployment exists/is contacted locally |
| AC-14 | toolchain manifest plus adb identity (`sdk=37`, `PAGE_SIZE=16384`, AVD `realm-api37-ps16k-kvm`, compat hard-fail flags) and runtime manifest binding | availability PASS; runtime execution mapped to runtime lane |
| AC-15 | G010 scope, publication/processor bytecode scans, supported task/runtime network trace, direct-validation privacy/static audit | mapped to Task 4/5/6 |

## Canonical local CI sequence

1. `tools/verify-toolchain.sh ...`
2. `python3 tools/g011-evidence-manifest.py --mode baseline --verify evidence/provenance/g011-source-evidence-manifest.json`
3. `tools/verify-g003-independent-builds.sh --run ...`
4. `tools/verify-g004-transformer-public-api.sh --run`
5. `./gradle-plugin/gradlew --project-dir gradle-plugin --no-daemon --console=plain cleanTest test`
6. locally generate an ephemeral signing key; `tools/publish_release.sh --signed-bundle`
7. `tools/g008-publication.py ... --require-signatures ...`; `tools/g011-consume-six.sh --mode local ...`
8. native ELF/ABI gate, AC07/AC08 local runtime gates, AC09 API gate, G010 scope/license gates, Portal/direct-validation tests.
9. seal checksums/runtime manifest; report every AC passed, failed, or external-gate pending.

## Preflight finding

The committed `evidence/provenance/g011-source-evidence-manifest.json` is stale at the exact integrated HEAD: five release gate digests differ. Raw diff is `logs/baseline-manifest.diff`. No shared file was edited; the leader was notified before any cross-lane remediation.
