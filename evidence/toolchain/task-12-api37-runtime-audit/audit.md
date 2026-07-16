# Task 12: API 37 / 16 KiB runtime and tool checksum availability

**Scope:** read-only support for task 10.  All observations were obtained on 2026-07-16 from the official Android/Gradle endpoints listed in `official-source-hashes.tsv`, and from `sdkmanager --list --verbose --channel=0` using the installed Google command-line tools.  No wrapper or production-source file was changed.

## Verdict

| Requirement | Result | Evidence / exact value |
| --- | --- | --- |
| API 37 platform package | **AVAILABLE under revisioned IDs** | `platforms;android-37.0` (revision 2) and `platforms;android-37.1` (revision 1) appear in `sdkmanager-target-extract.txt`. The literal `platforms;android-37` does **not** appear in the stable listing, so task 10 must use `platforms;android-37.1` rather than an unversioned ID. |
| API 37 16 KiB system image | **AVAILABLE** | `system-images;android-37.1;google_apis_ps16k;x86_64`, version 7, describes a “16 KB Page Size Google APIs Intel x86_64 Atom System Image” and requires emulator revision 36.5.11.  ARM equivalent: `...;arm64-v8a`.  Play Store variants are also listed. |
| Exact AVD configuration on this x86_64 WSL host | **READY TO PROVISION; NOT RUNTIME-PROVEN** | `avdmanager create avd --force --name realm_api37_16k --package 'system-images;android-37.1;google_apis_ps16k;x86_64' --device pixel_8`; boot then prove it with `adb shell getconf PAGE_SIZE` returning `16384`. Do not call the package listing itself a runtime pass. |
| Build Tools | **AVAILABLE** | `build-tools;36.0.0`, version 36.0.0. Google repository archive manifest: `build-tools_r36_linux.zip`, 63,737,259 bytes, XML SHA-1 `b0b6376977657e8ad9b969bacf4093601da2c6fb`. |
| NDK | **AVAILABLE** | `ndk;29.0.14206865`, version 29.0.14206865. Linux archive: `android-ndk-r29-linux.zip`, 783,549,481 bytes, XML SHA-1 `87e2bb7e9be5d6a1c6cdf5ec40dd4e0c6d07c30b`. |
| Android Emulator | **AVAILABLE** | Stable listing offers `emulator`, version 36.6.11; API 37 ps16k images require 36.5.11, so the listed stable package satisfies that minimum. |
| CMake 3.27.7 as an SDK package | **ABSENT / BLOCKER** | Exact `cmake;3.27.7` is absent both from `sdkmanager --list --verbose --channel=0` and from the fetched `repository2-1.xml`. Current Google XML lists CMake 3.22.1, 3.30.x, 3.31.x, and 4.x—not 3.27.7. Do not pretend `sdkmanager 'cmake;3.27.7'` can succeed. |
| Gradle 9.6.1 binary distribution | **VERIFIED** | Official `.sha256` and a local hash of downloaded `gradle-9.6.1-bin.zip` both equal `9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14`. |
| Current Google command-line tools | **REVISION IDENTIFIED; SHA-256 publication defect captured** | Official Android Studio table names `commandlinetools-linux-14742923_latest.zip` and labels its 40-hex value `48833c34b761c10cb20bcd16582129395d121b27` as “SHA-256.” A 40-hex string is not a SHA-256. Local hashes of the official 172,789,259-byte ZIP prove it is the **SHA-1**. Local SHA-256 is `04453066b540409d975c676d781da1477479dde3761310f1a7eb92a1dfb15af7`, but Google does not publish that 64-hex checksum in its current table, so it cannot be vendor-verified as SHA-256. |

## Safe provisioning command

```bash
sdkmanager \
  'platforms;android-37.1' \
  'build-tools;36.0.0' \
  'ndk;29.0.14206865' \
  'emulator' \
  'system-images;android-37.1;google_apis_ps16k;x86_64'

avdmanager create avd --force --name realm_api37_16k \
  --package 'system-images;android-37.1;google_apis_ps16k;x86_64' \
  --device pixel_8
emulator -avd realm_api37_16k -no-snapshot -no-audio -no-boot-anim &
adb wait-for-device
adb shell getconf PAGE_SIZE  # required acceptance value: 16384
```

This command deliberately omits `cmake;3.27.7` because the official repository does not expose it. Task 10 must record a recovery decision for that unavailable exact dependency; task 11 remains blocked until the AVD actually boots and returns `16384`.

## Reproduction

```bash
sdkmanager --list --verbose --channel=0
# Search the output for the package IDs in sdkmanager-target-extract.txt.
curl -fsSL https://services.gradle.org/distributions/gradle-9.6.1-bin.zip.sha256
curl -fsSL https://developer.android.com/studio
curl -fsSLO https://dl.google.com/android/repository/commandlinetools-linux-14742923_latest.zip
sha1sum commandlinetools-linux-14742923_latest.zip
sha256sum commandlinetools-linux-14742923_latest.zip
```
