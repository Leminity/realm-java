# Rollback

The pre-integration leader root is pinned by
`refs/omx/rollback/g013-ai-slop-chain-integration-20260721T134950Z-worker1` at
`6f089da04c48f129d38086bbe9ecad80bf6c4458`.

Before sharing the integration, a clean root may be restored by resetting the
`agp9.1` branch to that ref. After sharing, preserve history: revert the separate
integration evidence commit first, then revert original evidence-only commits
`0cebcbb95358b7c35063df00e8ffe02ab78d8ac0`,
`1e12ec9713555e5c34c82009c3b4075a82d9420a`, and
`10a2af980793e728fc41c9bf5bab61ad2f2b1d8b` in reverse order.

Do not revert exact root `6f089da04...` or prior G013 evidence. No source patch,
external state, publication state, or goal state requires rollback.
