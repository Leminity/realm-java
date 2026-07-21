# Task 4 acceptance matrix

| AC | Status | Evidence |
|---|---|---|
| AC-03 | PASS | G004 public AGP API static verifier/regression PASS; immutable run proves application/library Java/Kotlin debug+release transforms and configuration-cache reuse. |
| AC-04 | PASS | Immutable exact CI XML independently parsed: 48 tests, 0 failures/errors, 11 expected skips, 12/12 application/library × Java/Kotlin/mixed × both plugin-order cells, four contracts per cell. |
| AC-07 | RUNTIME-LANE / NOT OWNED | Static API/generated-file prerequisites PASS here; bidirectional API37/16KiB runtime semantics remain owned by the runtime lane and are not weakened or claimed. |
| AC-09 | PASS | Six-artifact public API/resource report, official oracle digests, and four generated proxy/module hashes independently audited; G009 verifier regression PASS. |
