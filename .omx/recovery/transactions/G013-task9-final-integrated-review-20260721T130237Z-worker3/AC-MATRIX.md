# G013 final integrated local acceptance matrix

Exact source under test: 188f0832252172a5ca93204292a65a0f8fe4f4f3
Source tree: 4e99f91dfe86abbc957e5f9596de454d90c075aa
Realm Core: d7b52ccbada0283527db36143cfeab18692b4ed0
Integrated evidence parent: 7e3da3b708d5aa0c0f24ceca09358fc1eed4420d

| AC | Final local verdict | Evidence boundary |
|---|---|---|
| AC-01 | PASS | Exact JDK 17, Gradle 9.6.1 wrappers, AGP 9.1.1, SDK/target 37, minSdk 21, NDK 29.0.14206865, and CMake 3.27.7. |
| AC-02 | PASS | Independent build matrix 13/13; native outputs exactly armeabi-v7a, arm64-v8a, x86_64. |
| AC-03 | PASS | Public AGP API transformer and application/library Java/Kotlin debug/release fixtures. |
| AC-04 | PASS | Plugin suite 48 tests, zero failures/errors, 11 expected skips, all 12 parameter cells. |
| AC-05 | PASS | Supported-scope and dependency/runtime denylist gates have no forbidden hits. |
| AC-06 | PASS | Exact three ABIs, x86/Sync absent, all nine ELF PT_LOAD alignments 0x4000, zipalign -P 16. |
| AC-07 | PASS | Bidirectional official/fork plain and encrypted fixtures, wrong-key rejection, zero unexpected migration callbacks. |
| AC-08 | PASS | Exact API 37 / 16 KiB target; six full-semantics runtime tests plus force-stop restart. |
| AC-09 | PASS | Fresh official resolver/oracle compatibility, public API/resource and generated-file hashes, replayable logical/filesystem evidence. |
| AC-10 | PASS | Exact six signed/checksummed local coordinates, deterministic bundle, isolated fork-only consumer. |
| AC-11 | PASS | Six POM/license/dependency/SCM/developer metadata sets, sources, javadocs, signatures, checksums. |
| AC-12 | LOCAL CONTRACT PASS / EXTERNAL STAGE PENDING | Portal 32/32, direct-validation workflow 7/7, independent portal/redaction/workflow total 51/51. Protected environment/Central staging was intentionally not invoked. |
| AC-13 | EXTERNAL-GATE PENDING | Validated deployment, public Central publication, and public clean-consumer rerun require protected external authority; none was attempted locally. |
| AC-14 | PASS | Live SDK 37, AVD realm-api37-ps16k-kvm, PAGE_SIZE=16384, direct WSL2 execution, no compatibility fallback. |
| AC-15 | PASS | Scope/license/publication/privacy/static/network audits pass; no secret, private keyring, forbidden endpoint, or external mutation. |

## Aggregate verdict

- Local PASS: AC-01..AC-11, AC-14, AC-15.
- AC-12: local contract PASS; protected external stage pending.
- AC-13: external gate pending.
- Current local failures: none.
- No acceptance threshold was weakened.
- No upload, repository drop, tag, GitHub Release, Central stage/publish, public consumer, external mutation, or Ultragoal/Codex goal-state mutation was performed by Task 9.
