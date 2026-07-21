# Worker-1 sanitized acceptance summary

Final integrated source under test: `188f0832252172a5ca93204292a65a0f8fe4f4f3`
(tree `4e99f91dfe86abbc957e5f9596de454d90c075aa`) with Realm Core
`d7b52ccbada0283527db36143cfeab18692b4ed0`.

| AC | Worker-1 verdict | Sanitized evidence |
|---|---|---|
| AC-01 | PASS | Exact JDK 17, Gradle 9.6.1 wrappers, AGP 9.1.1, SDK/target 37, minSdk 21, NDK 29.0.14206865, and CMake 3.27.7 verified. |
| AC-02 | PASS | Independent build matrix 13/13; supported Realm native outputs are exactly armeabi-v7a, arm64-v8a, and x86_64. |
| AC-03 | PASS | Public AGP API transformer gate and application/library Java/Kotlin debug/release fixtures PASS, including configuration-cache reuse. |
| AC-04 | PASS | Plugin matrix: 48 tests, 0 failures/errors, 11 expected skips, all 12 parameter cells covered. |
| AC-05 | PASS | Supported-scope report has no forbidden runtime or supported-graph hits; local execution denylist checks PASS. |
| AC-07 | RUNTIME LANE / NOT OWNED | Static API and generated-file prerequisites PASS. Bidirectional API37/16KiB runtime semantics remain owned by the runtime lane and are not promoted to PASS here. |
| AC-09 | PASS | Official-oracle compatibility, public API/resource hashes, generated proxy/module hashes, logical digest inventory, and replayable filesystem seals PASS. |
| AC-10 | PASS | Exact six fork coordinates at `10.19.0-agp9.1`: 144 logical files/24 per coordinate, signed/checksummed sources+javadocs+POMs+primary artifacts; deterministic bundle and isolated local consumer PASS. |
| AC-11 | PASS | Six POMs and license cross-bindings PASS for normalized dependencies, Apache-2.0, `realm-java` URL/SCM, developer metadata, signatures, and checksums. |
| AC-15 | PASS | Scope/license/publication regressions, privacy checks, and local network/action audits PASS; no external mutation occurred. |

## Current failures and external gates

- Current failures in the worker-owned criteria above: **none**.
- Task 1 transparently recorded two stale generated-manifest checks at the original
  integrated source. The approved canonical one-file provenance refresh commit
  `188f0832252172a5ca93204292a65a0f8fe4f4f3` resolved them; post-refresh verification
  passes. Task 2 retains one pre-commit manifest-unit finding and its succeeding
  post-commit PASS as audit history, not as a current product failure.
- Outside this Task 6 verdict, AC-06/AC-08 runtime execution and AC-14 runtime
  binding remain owned by the runtime lane; AC-12 is local-contract PASS only;
  AC-13 remains **EXTERNAL-GATE PENDING**. No protected external action was attempted.
