# Rollback

Task 4 made no source, build logic, workflow, or runtime change. The source under
test remains 188f0832252172a5ca93204292a65a0f8fe4f4f3 with tree
4e99f91dfe86abbc957e5f9596de454d90c075aa; Task 2 evidence commit
285617b195f03d703795115f5ada8de14b4d1e60 is the evidence parent.

Before commit, rollback is removal of only the Task 4 transaction directory.
After commit, revert the single Task 4 Lore evidence commit. No production
rollback patch exists because the verified source diff is empty. The empty
rollback/no-source-change.patch is the machine-checkable source-change artifact.
