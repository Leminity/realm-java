# Task 8 executable-fixture status: BLOCKED before G002

## What passed in this evidence-only lane

1. The repository-root checksum command documented in `../README.txt` now passes:
   ```sh
   sha256sum --check evidence/oracle/official-10.19.0/checksums/sha256sum.txt
   ```
   Its exact PASS output is retained in `root-sha256sum-check.txt`.
2. `compatibility-fixtures/official-10.19.0-generator/` contains an isolated Android
   instrumentation generator that pins **only the official Realm Java 10.19.0** plugin
   and runtime coordinates. Its schema/data assets, fixed semantic read assertions, and
   scripts parse successfully; see `static-validation.log`.
3. The generator test creates both `official-10.19.0-plain.realm` and
   `official-10.19.0-encrypted.realm`, records schema/data/key/fixture/toolchain
   fingerprints, and reopens each with the same official 10.19.0 reader before writing
   `fixture-manifest.json`. It will not accept an absent or malformed 64-byte test key.

## Why no fixture PASS is claimed

No `.realm` files or `fixture-manifest.json` exist under the generator's ignored
`generated/` directory. The runtime command was deliberately not run because its
preconditions are absent:

- `adb devices -l` returned zero devices.
- `$HOME/Android/Sdk/emulator/emulator` is absent.
- `$HOME/Android/Sdk/cmdline-tools/latest/bin/sdkmanager` is absent, so this lane cannot
  install a system image or missing platform through the supported SDK command line.
- The only installed platform is `android-36.1`; the binding target is SDK/API 37.
- The isolated Gradle 7.5/AGP 7.4.0 preflight was intentionally attempted offline and
  failed because required AGP transitive modules are not cached. The complete command
  and output are in `gradle-assemble-preflight.log`.

The generator is therefore prepared but **BLOCKED**, not PASS. The encryption key hash
cannot be frozen until an actual runtime generation uses the approved test-only key;
the test will emit it in `fixture-manifest.json` without writing key material.

## Narrow prerequisite for G002

Use the approved G002 bootstrap—not task 8—to provide the binding runtime: JDK 17,
Gradle 9.6.1, AGP 9.1.1, SDK/build-tools/API 37, NDK 29.0.14206865, Android command-line
tools, an API 37 emulator/system image (or an attached API 37 device), and `adb` access.
Then run the command below with a test-only secret key, pull the output, and verify the
manifest and both fixture SHA-256 values:

```sh
cd compatibility-fixtures/official-10.19.0-generator
export ANDROID_HOME=/path/to/sdk
export FIXTURE_KEY_HEX="$(openssl rand -hex 64)" # save only in approved secret storage
./run-official-oracle.sh
```

No production source or `.omx/ultragoal` file was changed by this task.
