# Rollback

This worker owns only the evidence transaction at `.omx/recovery/transactions/G013-independent-review-remediation-20260721T143111Z-worker3`; it does not modify Realm source, public API, build logic, workflow files, license/notice files, or publication state.

- Before commit: delete only `.omx/recovery/transactions/G013-independent-review-remediation-20260721T143111Z-worker3` and delete the unique rollback ref with `git update-ref -d refs/omx/rollback/g013-independent-review-worker3-20260721T143111Z`.
- After commit: revert only the eventual worker-3 evidence commit; do not rewrite history and do not revert worker-1 or worker-2 remediation commits.
- The preserved pre-operation source is `refs/omx/rollback/g013-independent-review-worker3-20260721T143111Z`, which resolves to `36f5346e8a0841ac6af09a391bd45902b1be0091`.

No Maven Central or GitHub external action is part of rollback.
