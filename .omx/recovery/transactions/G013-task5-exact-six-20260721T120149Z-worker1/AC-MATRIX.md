# Task 5 acceptance matrix

| AC | Status | Evidence |
|---|---|---|
| AC-10 | PASS | Exact six `io.github.leminity.realm` coordinates at `10.19.0-agp9.1`; 24 files each/144 logical files, six primary artifacts, six sources, six javadocs, six POMs, 24 detached signatures, and 96 checksum sidecars. All 143 retained files were rehashed; the single compacted base AAR is cross-bound by its manifest, retained SHA-256 sidecar, license report, omitted-payload record, and bundle inventory. Six POMs have exact Apache-2.0, `realm-java` URL/SCM, Leminity developer, and normalized dependency metadata with no `io.realm` dependency. |
| AC-11 | PASS | Logical inventory and deterministic bundle listing each cover all 144 paths; captured bundle SHA-256 is `1fc4bcfddb24a214ed89f646007bbe14cb466924bfb948c65a64309253678cf0`. The isolated local exact-six consumer exits 0 with exclusive fork dependency/plugin resolution, no Maven Local/JitPack, and `G011 exact-six consumer: PASS`. |
| AC-15 | PASS | G010 scope/license reports and fresh regression suites PASS; this Task 5 replay performed local read/verification only, changed no source, and performed no upload, drop, tag, release, Central stage/publish, or other external mutation. |
