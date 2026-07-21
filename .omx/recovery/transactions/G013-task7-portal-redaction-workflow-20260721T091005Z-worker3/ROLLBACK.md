# Rollback

This transaction adds only this local evidence directory and changes no production source.
Before integration, rollback is deletion of this directory. After integration, use a normal git revert of the evidence commit.
No upload, drop, tag, GitHub release, Central stage/publish, or goal-state mutation is part of this transaction.
