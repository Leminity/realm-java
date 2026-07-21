# Baseline independent review

Exact review root: `36f5346e8a0841ac6af09a391bd45902b1be0091`.

## Confirmed defects before remediation

1. **GitHub Actions trust boundary — FAIL.** `.github/workflows/ci.yml` enables `pull_request` and the only job runs on `[self-hosted, linux, api37, ps16k]` without a push-only job condition. A fork or same-repository pull request can therefore cause untrusted checked-out code to execute on the persistent release-capable runner.
2. **Fork identity — FAIL.** The README's Maven Central badge targets the upstream `io.realm` coordinate and its license badge links to the upstream repository rather than this fork's local `LICENSE`, despite the later maintenance-fork paragraph.
3. **Tracked interpreter output — FAIL.** The exact tree contains two tracked `.pyc` files under `tools/__pycache__/`, and `.gitignore` has no Python bytecode rule.
4. **Baseline verifier compatibility — FAIL.** `tools/verify-baseline.sh` does not approve README/NOTICE modification-notice repairs, so legitimate compliance changes would fail closed until the exact allowlist and regression tests are updated.
5. **Provenance coupling — integration risk.** `.github/workflows/ci.yml` is bound by `tools/g011-evidence-manifest.py`; any workflow remediation must refresh the committed baseline manifest and reconcile existing workflow assertions. New compliance/trust-boundary regression tests should be provenance-bound rather than left outside the gate list.

## Preserved constraints

No Realm public API, Realm file-format code, product source, ABI list, Gradle/AGP/SDK/NDK/JDK pin, publication endpoint, credential, or deployment identifier is changed by this review lane.

## Canonical-root recovery finding

During the review, the canonical `agp9.1` branch had advanced through accidental commit `665dbcd89e03922b2d6c859bad013921e48a848a` and merge `ed12cfc5594e41637c18a9e1898ec4dff72dab98`. Their only source delta changed the Realm Core gitlink from required `d7b52ccbada0283527db36143cfeab18692b4ed0` to `f8752e180b7f288feadffafdef818068755efe0a`. The leader explicitly authorized recovery; worker 3 preserved rollback refs and reset only the leader branch/worktree to the exact authoritative root. The checksum-verified recovery record is `.omx/recovery/transactions/G013-accidental-team-recovery-20260721T144655Z-worker3` in the leader root. Neither accidental commit is now an ancestor of `agp9.1`.
