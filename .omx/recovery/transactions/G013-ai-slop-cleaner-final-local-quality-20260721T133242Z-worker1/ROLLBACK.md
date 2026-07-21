# Rollback

This final quality stage adds only one evidence transaction across three local
commits. It changes no production source, build logic, dependency, workflow,
publication state, external state, `.omx/ultragoal` state, or Codex goal state.

Before integration, discard the worker branch. After integration, revert only
the following evidence commits in reverse order:

1. the enclosing `task: seal final local slop cleanup` Lore commit;
2. `1e12ec9713555e5c34c82009c3b4075a82d9420a`;
3. `10a2af980793e728fc41c9bf5bab61ad2f2b1d8b`.

Preserve exact integrated root
`6f089da04c48f129d38086bbe9ecad80bf6c4458` and all prior G013 evidence. The
`rollback/no-source-change.patch` file is intentionally empty because this
stage makes no source change.
