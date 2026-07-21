# Historical independent-review probes

All entries below are preserved read-only audit-probe corrections, not product failures and not mutations of peer evidence.

## Task 5 schema probes

1. A probe initially treated JSON object iteration order as coordinate semantic order. The corrected audit used coordinate identity and exact key sets.
2. A probe expected a top-level mode key. The exact manifest schema contains only artifacts, coordinates, dynamic_plugin_injection, files, format, group, normalized_pom_dependencies, and version.
3. A probe searched result.txt for consumer routing/fork group. The corrected audit used routing-proof.txt; result.txt records only the Gradle exit.

The corrected schema-aware Task 5 audit passed and the frozen evidence was not edited.

## Task 6 frozen-review probes

1. A probe expected worktree-proof.json[source_commit]; the exact schema uses source_under_test.
2. A probe expected the literal Lore value Task 6; the exact Lore field is Lore-Task: 6.
3. Two probes overfit literal rollback wording and an unnormalized newline. The corrected review evaluated semantic scope across ROLLBACK.md, execution-audit.json, and the evidence-only commit path set.
4. A probe assumed the Core gitlink path was core; the exact path is realm/realm-library/src/main/cpp/realm-core.
5. A bounded git diff-files --quiet check timed out on WSL/NTFS. The corrected clean-worktree verdict used bounded git diff-index --quiet HEAD --, standard-untracked enumeration, exact HEAD, and a clean exact Core checkout.
6. An active Ultragoal/Codex goal state is expected. The final verdict proves no Task 6 mutation using execution-audit.json and commit scope; it does not assert goal-state absence.

The corrected Task 6 independent verdict is PASS at immutable commit bb3416016a6d2cceb612bffb55f5e6aea84fb690. No Task 6 transaction or goal state was edited.

## Task 9 integration precondition

The Task 9 verifier was intentionally drafted before root integration. Its first execution at pre-integration head ef8ed3f52ece1a092bc2480533656bba4e76609f is retained as an expected precondition failure because the exact Task 2/4/5/6 commits were not yet ancestors. Task 10 owns the no-fast-forward root merge; the final Task 9 PASS must bind the reported post-merge head and require all eight integrated evidence commits as ancestors, preserve the original worker-1 hashes as ancestors, and prove the Task 3/7/8 integrated transaction subtrees are byte-identical to their original worker commits.
