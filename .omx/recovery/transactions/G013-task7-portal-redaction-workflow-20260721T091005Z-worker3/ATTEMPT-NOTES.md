# Attempt notes

- A preliminary Python replay generated four bytecode-cache files that an automatic checkpoint captured. The cache-only checkpoint was reset and excluded before the authoritative replay; none of those four files is present in this evidence commit.
- The authoritative 51-test replay uses `PYTHONDONTWRITEBYTECODE=1` and exact parent `d39316930fd63e379b58bc6296696781099ca4c7`.
- An exploratory full G011 baseline-manifest verification was removed from the acceptance set after it reported a manifest mismatch and the leader confirmed Core/native provenance is worker-2-owned and out of Task 7 scope. Task 7 provenance is instead bound directly to the exact root HEAD, core gitlink, plan/spec hashes, and relevant portal/workflow source hashes.
- `tools/verify-g010-scope.py` was also excluded from Task 7 acceptance because it traverses Realm Core history and fails when this portal/privacy worker intentionally leaves Core uninitialized. The required Task 7 `static.realm.io` audit is performed directly against the production processor subtree and supported portal/release surfaces.
- The first checksum pass accidentally listed its own temporary manifest. The final pass excludes the temporary name, regenerates `SHA256SUMS`, and records a fresh successful `CHECKSUM-VERIFY.log`.
