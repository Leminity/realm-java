# Lore — G013 pull-request runner trust boundary

Lore-Task: 1
Lore-Worker: worker-1
Lore-Pre-Head: 36f5346e8a0841ac6af09a391bd45902b1be0091
Lore-Trust-Boundary: untrusted pull-request code is limited to GitHub-hosted Ubuntu; the persistent API37/ps16k release-capable runner is reachable only from exact agp9.1 pushes
Lore-Workflow-Split: .github/workflows/ci.yml is trusted-push-only; .github/workflows/pull-request.yml runs the focused static runner-policy regression
Lore-Regression: a repository-wide parser rejects any PR-triggered job without a literal GitHub-hosted Ubuntu runner and locks the exact trusted CI branch
Lore-Verification: 3 trust tests, 1 existing CI contract test, 7 direct-validation tests, and 32 portal tests pass; Python compile/tabnanny/line length, YAML parse, diff check, toolchain pins, and unchanged release workflow pass
Lore-Known-Shared-Failure: the full G011 manifest suite remains lane-2-owned because an uninitialized Core checkout resolves to the outer HEAD; its dirty-runtime guard also intentionally rejects this pre-commit tree
Lore-Preparation-Incident: an unquoted rollback-document heredoc briefly invoked local ci.yml; the process tree was terminated, the only tracked pyc side effect was restored, and no GitHub/release/Central action or credential access occurred
Lore-Delegation: adapted role-intent recording was rejected with parent_not_active_leader; no role/model routing was fabricated, and direct scope stayed bounded
Lore-External-Actions: none
Lore-Goal-Mutation: none
Lore-Rollback: use the preserved ref from PRE and a normal inverse commit/revert; never rewrite history
