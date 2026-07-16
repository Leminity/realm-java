# Android 17 WSL2 Toolchain Evidence

This directory records the reproducible prerequisite recovery for the Realm
AGP 9.1.1 migration. It deliberately preserves the exact package identifiers
advertised by the configured Google repository: `platforms;android-37.0` and
`system-images;android-37.0;google_apis_ps16k;x86_64`. The missing literal
`platforms;android-37` is a repository naming detail, not a lowered SDK level.

## Pinned components

| Component | Pin / source | Evidence |
| --- | --- | --- |
| JDK | OpenJDK 17.0.19 | `java-version.txt`, `environment-diagnostics.txt` |
| Android command-line tools | revision 14742923; Google-published SHA-1 `48833c34b761c10cb20bcd16582129395d121b27` | `commandline-tools.sha1`, `commandline-tools.sha256` |
| Android SDK | Platform API 37.0, Build Tools 36.0.0, NDK 29.0.14206865, platform-tools, emulator | `sdkmanager-list-verified.txt` |
| CMake | 3.27.7 from `https://cmake.org/files/v3.27/cmake-3.27.7-linux-x86_64.tar.gz`; SHA-256 `a8c92ecb139bcc7a1f92a8108179bd1d021bdb158a5ee759cba6d60010b83ae9` | `cmake-3.27.7-*` |
| Gradle | 9.6.1 bin ZIP SHA-256 `9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14` | `gradle-wrapper-versions.txt`, wrapper properties |
| 16 KiB runtime | API 37.0 `google_apis_ps16k` x86_64 image, AVD `realm-api37-ps16k` | `emulator-final-runtime.txt`, `emulator-final-logcat-tail.txt` |

`cmake;3.27.7` is absent from current stable `sdkmanager` metadata. The
bootstrap script therefore verifies and extracts the official Kitware archive
into the standard SDK side-by-side location (`$ANDROID_SDK_ROOT/cmake/3.27.7`)
rather than selecting a different CMake version.

## WSL2 emulator runtime recovery

On this WSL2 host, the emulator launcher initially lacked optional host shared
libraries (`libpulse0`, `libnss3`, and `libxkbfile1`). They were downloaded as
unprivileged Ubuntu packages and extracted beneath
`$HOME/.local/realm-emulator-libs/root`; no system packages or privileges were
changed. `libpulse0-deb.sha256` records the initial Pulse archive;
`emulator-runtime-debs.txt` and `emulator-runtime-debs.sha256` record the
additional exact package archives. `tools/verify-toolchain.sh` automatically
adds that directory to `LD_LIBRARY_PATH` when it exists, allowing
`emulator -version` to verify the installed emulator.

## Validation

- `agp91-platform-probe.log` shows AGP 9.1.1 resolving both `compileSdk` and
  `targetSdk` to 37.
- `emulator-final-runtime.txt` records API 37 and `getconf PAGE_SIZE=16384` on
  the running `sdk_gphone16k_x86_64` device.
- `verification.txt` records `tools/verify-toolchain.sh` passing after the
  local runtime recovery.
