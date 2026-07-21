# G008 local publication evidence

The exact-six signed local staging repository and deterministic Central-format
bundle were built and fully verified before this transaction was sealed.

publication-manifest.json is the canonical six-coordinate file/digest manifest.
staging-captured-logical-inventory.sha256 and staging-captured-sizes.txt record
the complete staging snapshot before compacting. bundle-captured.sha256,
bundle-captured-size.txt, and bundle-captured-listing.txt bind the bundle.

To follow this repository's compact committed-evidence convention, only the
large realm-android-library primary AAR and the reproducible bundle ZIP are
omitted after validation. OMITTED-PAYLOADS.txt records their exact size/hash.
POMs, sources, javadocs, signatures, checksums, other primary artifacts, logs,
license report, consumer proof, and native ELF report remain materialized.
The captured inventory is historical and is not a replayable filesystem seal.
The transaction-level SHA256SUMS is the replayable seal for retained evidence.
