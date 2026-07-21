# Lore — Task 7 independent portal/privacy replay

## Context

The final G013 local gate requires an independent replay of the portal, redaction, workflow, privacy, and provenance contracts at exact integrated parent `d39316930fd63e379b58bc6296696781099ca4c7`.

## Invariants

- No upload, drop, tag, GitHub release, Central stage/publish, or goal-state mutation.
- Portal results use explicit sanitized result files, never raw tee output.
- The exact authenticated VALIDATED consumer receives only the named bearer contract.
- Non-protected retained evidence binds repository identity by hash only and recursive scans fail closed on secret/repository/deployment identifiers.
- Supported release surfaces contain no executable retired `static.realm.io`, old OSSRH, or S3 endpoint.

## Decision and evidence

- Replayed `32` portal tests and `19` redaction/workflow tests: `51/51 PASS`.
- Verified Python AST/tabnanny, Bash syntax, release YAML parsing, workflow scan exemptions, opt-in-only network contract, targeted retired-endpoint absence, exact source HEAD, unchanged relevant source, and recursive transaction privacy.
- A bounded independent probe confirmed commands and evidence thresholds before final sealing.

## Recovery

The commit is evidence-only. Revert it normally after integration; before integration, deleting only this fresh transaction directory is sufficient. Production source is unchanged.
