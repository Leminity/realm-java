# Rollback instructions

Pre-change source is preserved by the rollback ref recorded in `PRE`.

To revert after integration without rewriting history:

1. Restore `.github/workflows/ci.yml` from `rollback/ci.yml.pre`.
2. Remove `.github/workflows/pull-request.yml` and `tools/test-g013-workflow-trust.py` when their matching `.ABSENT` markers are present.
3. Commit the inverse change with a new Lore-formatted revert commit; do not reset or force-push.
4. Re-run `python3 tools/test-g013-workflow-trust.py` and the focused G011 manifest tests.
