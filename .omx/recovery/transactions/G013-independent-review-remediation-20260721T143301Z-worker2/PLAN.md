# G013 worker-2 remediation plan

1. Lock exact-root behavior and enumerate the upstream-to-fork file delta without mutating production source.
2. Add focused regression checks for fork identity, Apache-2.0 modification notices, baseline verifier coverage, and Python bytecode hygiene.
3. Apply the smallest compatible documentation/verifier/ignore changes and remove only tracked generated `.pyc` files.
4. Run targeted tests, syntax/static checks, relevant Gradle checks, and privacy/source-contract regression checks.
5. Commit the remediation with Lore trailers, seal POST/COMMITTED/SHA256SUMS/rollback evidence in a separate Lore-formatted evidence commit, and report exact hashes.
