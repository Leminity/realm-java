# AC-08 API 37 / 16 KiB runtime harness

This isolated two-app instrumentation harness consumes the immutable official 10.19.0
baseline and the G008 local Maven-layout repository. `run-ac08.sh` is the only intended
entrypoint: it runs offline, locks the shared API 37 ps16k emulator, verifies its identity,
creates the official schema-N input, runs the fork runtime suite, then writes checksummed
raw evidence. It never uses JitPack, Maven Local, or a Maven Central publication action.

The apps intentionally use different packages (`io.realm.ac08.official` and
`io.realm.ac08.fork`) and different Gradle builds. The official lane is pinned to the
unchanged upstream `io.realm:10.19.0` plugin/runtime and its original AGP 7.4/Gradle 7.5
compatibility lane. The fork lane retains AGP 9.1 and resolves only
`io.github.leminity.realm:10.19.0-agp9.1` from the supplied G008 file repository.

The fork exercises ordinary runtime semantics through `DynamicRealm`, while its static
N+1 model proves an upstream official schema-N file performs exactly one migration and
persists the transformed value after reopen. Before device work, the runner rejects any
non-successful instrumentation report; all device operations use `emulator-5654` under
`/tmp/realm-g009-device.lock`.
