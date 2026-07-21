# Bounded AI-slop cleanup plan

## Authority

- Approved plan: `.omx/plans/realm-java-android17-agp9-mavencentral.md`
- Test specification: `.omx/plans/test-spec-realm-java-android17-agp9-mavencentral.md`
- Context: `.omx/context/realm-java-android17-20260716T004500Z.md`
- Behavior lock: `BEHAVIOR-LOCK.md` and the sealed G013 Task 9 review.

## Scope boundary

Inspect only source-bearing paths changed after
`188f0832252172a5ca93204292a65a0f8fe4f4f3` at the exact integrated root
`6f089da04c48f129d38086bbe9ecad80bf6c4458`. Exclude `.omx/**`,
`evidence/**`, and other transaction/evidence-only files. Do not review the
whole upstream fork and do not edit production source unless the inventory
proves a concrete build-fix-related slop defect with regression coverage.

## Ordered passes

1. Enumerate the eligible changed-file set and prove the exclusions.
2. Search eligible files for fallback-like signals: quick/temporary hacks,
   workaround or bypass branches, swallowed failures, silent defaults, broad
   compatibility shims, and duplicate alternate execution paths.
3. Classify each finding as masking fallback slop or grounded
   compatibility/fail-safe behavior; record tests and escalation status.
4. Inventory dead code, duplication, needless abstraction, naming/error
   handling issues, boundary violations, debug leftovers, and missing tests.
5. Apply no source change unless a finding is both inside scope and tied to a
   concrete build-fix defect with regression coverage. Otherwise record a
   no-change disposition.
6. Re-run the smallest source/tree/Core, checksum, lint/static, and targeted
   test gates that prove the final local quality claim.
7. Seal PRE/POST/COMMITTED/SHA256SUMS/rollback and Lore evidence without an
   external action or goal-state mutation.

## Stop conditions

- Stop source editing when the eligible source-bearing set is empty or all
  findings are grounded, out of scope, or lack a proven build-fix defect.
- Preserve exact source commit/tree/Core constraints.
- Do not add dependencies, broaden the refactor, stage/publish externally, or
  mutate `.omx/ultragoal` / Codex goal state.
