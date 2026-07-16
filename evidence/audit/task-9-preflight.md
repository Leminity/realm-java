# Task 9 Final G001 Acceptance Audit — PASS

**Disposition: accepted.** This audit independently re-ran every G001
provenance, fixture, checksum, source-boundary, ledger, and negative-diff gate
against the terminal task-11, task-15, and task-16 commits.

## Provenance and source boundary

- `git remote get-url origin` returned
  `https://github.com/Leminity/realm-java.git`; upstream returned
  `https://github.com/realm/realm-java.git`; unauthenticated
  `git ls-remote --exit-code origin HEAD` passed.
- `git rev-parse v10.19.0^{commit}` is
  `0ab8d6961afb038d0e0c69478de45dda3958d641`.
- `./tools/verify-baseline.sh` passed after task-16 commit
  `3639092af5aed617e61db75a994a42872eef07c2`. It compares all immutable
  baseline fields semantically and separately enforces the exact eight approved
  Gradle 9.6.1 wrapper URL/SHA pins.
- `bash tools/test-verify-baseline.sh` passed its approved-tree check and
  adversarial production Java, production C++, unexpected-root, unapproved
  fixture, unapproved toolchain, wrong-wrapper-version, wrong-wrapper-hash,
  and non-wrapper-capture cases. The direct predicate also rejected
  `realm/src/main/java/io/realm/UnauthorizedAuditProbe.java`.
- `git diff --check v10.19.0...HEAD` passed. The tracked delta classification
  contains 176 evidence paths, 23 isolated fixture-harness paths, eight wrapper
  properties, seven named tooling paths, one root ignore file, and two ledgers;
  no other path class exists. No Java, Kotlin, C, or C++ production-language
  path changed outside `evidence/**` and `compatibility-fixtures/**`.
- `git submodule status --recursive` matched Realm Core
  `5533505d18fda93a7a971d58a191db5005583c92`, Catch
  `3f0283de7a9c43200033da996ff9093be3ac84dc`, sha-1
  `d9ae30f34095107ece9dceb224839f0dc2f9c1c7`, and sha-2
  `0e9aebf34101c6aa89355fd76ac9cd886735dee1`.
- `compatibility-change-ledger.md` and `production-diff-ledger.md` are present.

## Official 10.19.0 oracle evidence

- `./tools/test-verify-release-tag.sh` passed the strict tag/version policy.
- `sha256sum --check
  evidence/oracle/official-10.19.0/checksums/sha256sum.txt` verified all twelve
  official Maven artifact/POM files.
- Task 11 completed at
  `934fcb4e0616ff0d7564fd26db9d917fe4467ad5`. Its ten-entry execution-evidence
  checksum bundle passed.
- The approved G001-only fixture oracle ran on isolated KVM API 36 / 4 KiB.
  It produced a plain Realm, encrypted Realm, and manifest; this does not
  weaken the separate later API 37 / 16 KiB fork-runtime requirements.
- The independently calculated fixed-key SHA-256 is
  `fdeab9acf3710362bd2658cdc9a29e8f9c757fcf9811603a8c447cd1d9151108`.
  `verify-generated-fixtures.py` passed its official-reader manifest/key/hash
  checks. Fixture hashes are:
  - plain: `46ccf472ba5ae55edb22ae640075df006b377be738ce651abe7507641347b734`
  - encrypted: `792abb7cc4ef3aafe99fd091e0dcd4f1cb713800f60304cc9a4ca6c1d37a23df`
  - manifest: `3aa08c68d046ebb96079f12aa3a6985ef2cffff3827d6c9e18557565875d7344`
- The fixture manifest declares Realm `10.19.0` and
  `official_reader_semantic_validation: true`.

## Independent toolchain and verifier gates

- Task 13 recorded API 37, page size 16384, and all eight non-fixture Gradle
  wrapper pins at the official Gradle 9.6.1 SHA-256
  `9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14`.
- Task 15 repaired the strict non-production allowlist. Task 16 repaired the
  semantic baseline comparison so the immutable 7.5 baseline wrapper URLs are
  not conflated with the separately enforced approved 9.6.1 wrapper pins.
- Earlier official-generator API 37 / 16 KiB failures remain preserved as
  diagnostics only; they are not counted as fixture evidence and do not alter
  the G001 fixture boundary above.
