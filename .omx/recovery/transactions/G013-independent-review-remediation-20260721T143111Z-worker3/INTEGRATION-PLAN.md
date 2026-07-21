# Cross-lane integration plan

## Exact topology and patch boundary

- Exact root: `36f5346e8a0841ac6af09a391bd45902b1be0091`.
- Worker-1 semantic commit: `16d599003f640c687f1e0ce3b0eb7f2d26c8579a`.
- Provisional canonical commit: `8fd6c6ea21cd5e1a85a8d8d0a64cb1df4c0f90cf`, tree `6982ecce6ad8f3b5df6aae5ce968ffe5614ddf21`.
- Worker-2 equivalent pre-delta commit: `352cf2f0b7877b332b54a0da241b1cf1db1cc96f`, the same tree `6982ecce6ad8f3b5df6aae5ce968ffe5614ddf21`.
- Worker-2 missing provenance commit: `3ae097d2542f491e64ed6779f676fdf7856f6554`.
- Worker-2 missing transaction commit: `3a2a49263d58d274d035c5297276c8ba99e75284`, final tree `fe6a5dc9a766701f062cad7a961621c6568ea6a1`.

Because the two boundary trees are identical, canonical integration must apply only `3ae097d25` followed by `3a2a49263`. Replaying worker-2 source/attestation or worker-1 integration commits would duplicate content. Worker 3 does not mutate the shared canonical branch; the leader owns these two cherry-picks.

## Provisional checkpoint handling

No history rewrite is permitted in this team. Preserve `e69bb5882597455f750f475584f17900ceb65dfe` and `8fd6c6ea21cd5e1a85a8d8d0a64cb1df4c0f90cf` as provisional history for now. A later leader-owned semantic-history cleanup map must explicitly include `8fd6c6ea` and its redundant auto-checkpoint ancestry; rollback refs must be preserved before any such later rewrite.

Canonical ancestry from the exact root currently contains only worker-1 `16d599003`, provisional merge `e69bb5882`, and provisional snapshot `8fd6c6ea2`. The accidental Core-changing commits `665dbcd89` and `ed12cfc55` are not ancestors. No commits from the accidental list team or duplicate `g013-review-remediati` team are present in canonical ancestry.

## Mandatory local gates after integration

- YAML parse and focused trust-boundary regression test.
- Baseline verifier regression test and `tools/verify-baseline.sh`.
- License/scope regression tests.
- G011 source-manifest generator unit test and exact committed-manifest verification.
- Python AST/compile checks with `PYTHONDONTWRITEBYTECODE=1`; Bash syntax for changed shell files; `git diff --check`.
- Targeted Gradle/JVM compilation or the nearest already-supported compile gate proving source compatibility, without publication or external deployment.
- Transaction checksum replay and privacy scan for credentials/deployment identifiers.

All listed gates passed independently on worker-2 final content. After the leader applies the two missing commits, rerun the baseline verifier and G011 manifest verification once on canonical `agp9.1`, then integrate the worker-3 evidence-only commit.

## Rollback

Each peer lane must retain its own rollback ref and evidence transaction. If integration fails, revert the failing Lore commit(s) normally; do not rewrite history. This worker's evidence-only commit can be reverted independently.
