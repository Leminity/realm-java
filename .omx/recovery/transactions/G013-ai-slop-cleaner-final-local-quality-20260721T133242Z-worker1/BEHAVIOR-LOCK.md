# G013 behavior lock

The cleanup baseline is the exact integrated root
`6f089da04c48f129d38086bbe9ecad80bf6c4458`. The source under test remains
`188f0832252172a5ca93204292a65a0f8fe4f4f3`, tree
`4e99f91dfe86abbc957e5f9596de454d90c075aa`, with Realm Core gitlink
`d7b52ccbada0283527db36143cfeab18692b4ed0`.

Behavior is locked by the existing G013 final integrated review transaction
`.omx/recovery/transactions/G013-task9-final-integrated-review-20260721T130237Z-worker3`:

- `sha256sum -c SHA256SUMS`: PASS for every sealed Task 9 entry.
- AC-01 through AC-11: local PASS.
- AC-12: local contract PASS; protected external stage remains pending.
- AC-13: external gate remains pending.
- AC-14 and AC-15: local PASS.
- Current local failures: none.
- No external action or goal mutation is part of this cleanup stage.

The post-source range contains only evidence/transaction material. The cleanup
must not reinterpret historical failures as current regressions and must not
weaken any acceptance threshold.
