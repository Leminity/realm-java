# Rollback

This transaction adds evidence only; no production source changes are expected.
To remove the local evidence commit after integration, revert the evidence commit recorded in COMMITTED.
Before commit, remove only: .omx/recovery/transactions/G013-pre-publication-regression-20260721T090051Z-worker1
Build outputs and local caches are ignored and may be deleted independently.
