# Rollback

The exact pre-remediation root is pinned by `refs/omx/rollback/g013-independent-review-remediation-20260721T143301Z-worker2` at `36f5346e8a0841ac6af09a391bd45902b1be0091`.

Before sharing, restore a clean detached worker tree with `git reset --hard refs/omx/rollback/g013-independent-review-remediation-20260721T143301Z-worker2`.
After sharing, preserve history: revert the transaction-evidence commit first and the implementation commit second. Do not rewrite history.

This rollback is repository-local. No Maven Central, GitHub, credential, deployment, Ultragoal, or Codex goal state is changed by this task.
