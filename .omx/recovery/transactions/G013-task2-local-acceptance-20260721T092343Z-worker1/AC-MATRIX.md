# G013 Task 2 local build, API, publication, and static acceptance

Source HEAD: 188f0832252172a5ca93204292a65a0f8fe4f4f3
Integrated source base: d39316930fd63e379b58bc6296696781099ca4c7
Realm Core: d7b52ccbada0283527db36143cfeab18692b4ed0
External mutation: forbidden and not performed.

| AC | Result | Evidence |
|---|---|---|
| AC-01 | PASS | Task-1 exact toolchain verifier; G003 eight-wrapper/static verification and independent builds on Gradle 9.6.1/JDK17/SDK37/NDK29/CMake 3.27.7. |
| AC-02 | PASS | G003 independent-build matrix 13/13 logs; realm native build produced only armeabi-v7a, arm64-v8a, x86_64. |
| AC-03 | PASS | G004 transformer public-API static gate and application/library Java/Kotlin fixtures all PASS. |
| AC-04 | PASS | Exact G005 cleanTest test: 48 tests, 0 failures/errors, 11 expected skips, 12/12 parameter cells; G003 plugin metadata gate also PASS. |
| AC-05 | PASS | G010 scope report has empty forbidden runtime/supported-graph hits; root installRealmJava dry-run and execution-log denylist scan PASS. |
| AC-06 | LOCAL STATIC PASS | Native bundle verifier: exact three ABIs and 0x4000 PT_LOAD alignment. Runtime/device execution remains its owning lane. |
| AC-07 | NOT OWNED | Bidirectional runtime fixture belongs to the runtime lane; no claim made here. |
| AC-08 | NOT OWNED | API37/16KiB runtime suite belongs to the runtime lane; device identity was verified in Task 1. |
| AC-09 | PASS | Two fresh official resolver runs, canonical compatibility verifier and unit PASS; logical digest inventory classified and replayable filesystem seal independently reviewed PASS. |
| AC-10 | PASS | Signed exact-six local repository/bundle PASS; bundle SHA-256 1fc4bcfddb24a214ed89f646007bbe14cb466924bfb948c65a64309253678cf0; isolated exact-six consumer PASS. |
| AC-11 | PASS | G010 license/publication report PASS for POM, primary, sources, javadoc, Apache LICENSE/NOTICE, signatures and checksums across six coordinates. |
| AC-12 | LOCAL CONTRACT PASS | Portal unit 32/32 and direct-validation workflow unit 7/7 PASS; protected external actions intentionally not invoked. |
| AC-13 | EXTERNAL-GATE PENDING | No deployment/public-Central mutation or clean external consumer was attempted in this local-only lane. |
| AC-14 | AVAILABILITY PASS | Task-1 SDK37/PAGE_SIZE=16384/AVD identity PASS; final runtime binding belongs to runtime evidence lane. |
| AC-15 | PASS | G010 supported-scope gate, portal/direct-validation tests, privacy scan, and supported execution-log network denylist scan PASS. |

All Task-2-owned criteria AC-01..05, AC-09..11, and AC-15 PASS.
