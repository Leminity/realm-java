# AC-07 bidirectional official/fork Realm compatibility

This harness proves the contract in
`../official-10.19.0-generator/fixture-oracle-procedure.md` without changing an
oracle file in place.

## Boundaries

- **Official inputs:** an exported `official-10.19.0-oracle` directory from the
  isolated official-only generator. It is supplied via `--official-fixtures`,
  SHA-256 checked against its manifest, and copied read-only to a fresh ignored
  run directory.
- **Fork reader/writer:** `fork-consumer` compiles with AGP `9.1.1`, Gradle
  `9.6.1` (the repository wrapper), SDK/target `37`, minSdk `21`, and JDK 17.
  It consumes a pre-verified G008 local Maven-layout repository, never
  `mavenLocal`, JitPack, or a remote publication endpoint.
- **Official reverse reader:** the existing official `10.19.0` fixture project
  remains isolated from the fork package and resolves only `io.realm:*:10.19.0`.

`FixturePerson` intentionally has the original fully-qualified class name in
both reader projects. That keeps Realm's schema identity identical while the
fork application id/data sandbox remains distinct.

## Running

First obtain immutable official fixture files with the existing generator on
its documented API-36 / 4 KiB oracle device. Do **not** use the historical hash
log as a fixture substitute.

```sh
compatibility-fixtures/ac07-bidirectional/run-ac07.sh \
  --official-fixtures /absolute/path/official-10.19.0-oracle \
  --fork-repository /absolute/path/g008-local-repository \
  --fork-serial emulator-5654 \
  --official-serial emulator-5654
```

Each invocation creates an ignored `generated/ac07.*` directory before any
stateful action. Every completed stage has a log; a first failure exits without
removing the directory. The runner records device API/page-size, provenance
checks, immutable input hashes before/after, fork instrumentation results,
working-copy hashes, wrong-key rejection, and the isolated official reverse
reader result. It never deletes an existing app, oracle export, or device data.

In the coordinated G009 environment, `emulator-5654` and `localhost:5655` are
two transports to the same API-37 / 16 KiB device. The runner rejects the
second transport and holds `/tmp/realm-g009-device.lock` from the first app
install through reverse-reader instrumentation, so it cannot collide with
another compatibility lane.

## Encrypted cross-page-size recovery

The preserved first failure showed that the immutable 8 KiB encrypted oracle
(`792abb7c…`) could not be opened on the API-37 / 16 KiB device even by the
isolated official `io.realm:realm-android-library:10.19.0` reader, with the
manifest-matched 64-byte key. A newly-created encrypted Realm did open and
reopen with the fork. This isolates the failure to reading an encrypted file
created with a smaller system page size, rather than to the key, the oracle
copy, or ordinary fork encryption.

The required Core change is a narrow backport of upstream
[`c97091234` (RCORE-1969/#7535)](https://github.com/realm/realm-core/commit/c97091234d40efaaaf7d8d8349eb3c97012f6c9b),
recorded in the Core submodule commit `d7b52ccb`. It preserves the fixed 4 KiB
encrypted on-disk block layout while allowing an encrypted file's mapping and
logical size to be rounded for the reader's page size. The upstream regression
`EncryptedFile_Portablility` writes at 4 KiB then reads at 8 KiB and 16 KiB;
it is part of the backport and must pass before the device matrix is accepted.
No oracle, encryption key, public API, file format, API level, or toolchain is
changed. Roll back this recovery by reverting the parent gitlink commit and
the `d7b52ccb` Core commit together.

### Verified recovery evidence

The clean API-37 / 16 KiB rerun at
`generated/ac07-c970-full-rerun-20260717T010733Z` passed all gates after the
backport. The fork opened the immutable plain and encrypted inputs with zero
migration callbacks, completed CRUD plus reopen, and rejected the wrong key;
the isolated official reader then opened the fork-modified copies without
migration. The copied inputs and the authoritative source still match:

- plain: `46ccf472ba5ae55edb22ae640075df006b377be738ce651abe7507641347b734`
- encrypted: `792abb7cc4ef3aafe99fd091e0dcd4f1cb713800f60304cc9a4ca6c1d37a23df`
- key: `5ec612cfb7275948c77e50b42aec317ba735523923823b11192fe6eb3826bb58`

The fresh local six-coordinate stage used for that rerun has manifest SHA-256
`63c145a3f032a19f58df03d71f2f83837e14a5945be48be1b524a56d3d026fae` and
`realm-android-library` AAR SHA-256
`ab058cd6cc942a18bb8bf86d63ed5fd87788cbcf3ee252e8b59b229afb0ee3bd`.
`g008VerifyLocalStaging` and the isolated `g008-clean-consumer.sh` both pass.
The unsuccessful pre-rerun launch at `ac07-c970-full-20260717T010621Z` ended
during fork assembly before device mutation and remains preserved separately
in ignored raw evidence; it is not used as recovery proof.
