# Rollback

This transaction adds only the local directory .
Before integration, rollback is deletion of that directory. After integration, use a normal git revert.
Peer source commits and evidence are read-only inputs and are not modified by rollback.
