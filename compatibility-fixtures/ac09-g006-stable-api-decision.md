# G006 AC-09 stable API classification — superseding decision

Status: ACCEPTED, NON-WEAKENING.

This transaction supersedes only the overly broad **raw class inventory must be byte-for-byte/class-for-class identical** clause in the earlier `base-aar-sync-objectserver-criterion-reconciliation-20260716T155233Z` decision. It does not delete or rewrite that historical decision. Its generic ObjectServer/Sync name-ban correction and supported-graph exclusion gate remain valid.

Binding contract:
- The interview specification requires Java/Kotlin **public APIs and package names** under `io.realm` to remain compatible.
- AC-09 requires zero unintended changes to the upstream **public** `io.realm` API/package/resource baseline.
- The mandatory G003/G005 toolchain uses Kotlin 2.2.10 built-in Kotlin under AGP 9.1.1; lowering compiler version is forbidden.

Accepted gate:
1. Official 10.19.0 vs candidate accessible public/protected class inventory is exact.
2. Their `javap -protected` signature manifests are exact.
3. Manifest minSdk21 and public resource/R inventories are exact.
4. Any raw class delta is diagnostic and must be exhaustively classified as non-accessible compiler implementation output, source-unchanged, pre-transform, and absent from public/protected signatures.
5. Transformer stripping must remove only the seven approved direct @ObjectServer types from the pre-strip artifact, leave the classified raw delta unchanged, and add no classes.
6. Supported graph/native/network exclusion gates remain independently mandatory.

Observed and approved diagnostic delta:
- 26 official-only `InternalFlowFactory` nested lambda class files.
- Every class has `ACC_FINAL|ACC_SUPER` and neither `ACC_PUBLIC` nor `ACC_PROTECTED`.
- The exact 26 are missing both before and after RealmBuildTransformer; therefore Task16 did not remove them.
- Source is unchanged. Official bytecode carries Kotlin metadata 1.6.0; required candidate bytecode carries metadata 2.2.0 and uses invokedynamic lambda lowering.
- Candidate has zero raw extra classes after stripping.

Result:
- Task6 and independent Task17 both PASS the binding AC-09 public API/resource contract.
- Recreating obsolete private Kotlin lambda class files through Realm product-source edits is forbidden as unrelated semantic/toolchain distortion.
- Any future public/protected signature/resource difference remains a hard blocker.

Rollback: if canonical spec/plan is explicitly changed, append a new decision; never mutate this audit record. No source, artifact, or external publication was changed by this classification.
