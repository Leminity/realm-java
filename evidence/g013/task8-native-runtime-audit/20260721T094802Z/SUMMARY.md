# Task 8 — Independent native/runtime evidence audit

## Verdict

**PASS.** Task 3 is a 94-path evidence-only Lore commit directly atop exact source d39316930fd63e379b58bc6296696781099ca4c7. The exact API37/16 KiB target was available and revalidated, so no unavailable-target exception or weakened fallback was used.

## Independent replay

- Re-ran tools/g011-verify-native-elf.sh against the fresh AAR: exact ABIs armeabi-v7a, arm64-v8a and x86_64; all nine PT_LOAD alignments are 0x4000.
- Recomputed AAR and APK SHA-256 values and matched Task 3. Re-enumerated native entries: exact expected set, x86 absent.
- Re-scanned all three native libraries for Sync patterns: none found.
- Re-ran zipalign -v -c -P 16 4: verification successful.
- Re-read the live target: SDK 37, AVD realm-api37-ps16k-kvm, PAGE_SIZE=16384.
- Replayed the Task 3 top-level checksum manifest (90/90) and AC-08 nested manifest (28/28).
- Audited AC-07 markers for bidirectional compatibility, immutable input, wrong-key rejection and zero unexpected migration callbacks.
- Audited AC-08 markers for official 1/1, fork 6/6, migration-once/reopen, wrong-key, notification/unsubscribe, thread confinement, force-stop restart, and disabled compatibility fallback.
- Re-ran native verifier tests (3/3) and AC-08 parameterization tests (6/6).

No production source was edited and no external action was performed.
