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

For the real-process restart gate, phase A instrumentation commits named/date/binary
sentinels to separate plain and encrypted local Realm files and writes its Android PID. The
host verifies that PID, force-stops only the fork package, proves it is gone, then runs phase B
instrumentation. Phase B reopens and validates both sentinels and records a distinct PID; both
phase files and the PID assertions are included in the checksummed evidence.

## G011 repository modes

The default no-argument command is the original **local** acceptance lane: it uses the
G008 filesystem stage and remains offline. G011 adds two explicit remote modes without
changing the apps or their runtime assertions:

- `validated` accepts exactly one HTTPS deployment download URL and a *name* of an
  environment variable containing the Bearer token. It requires a caller-supplied empty
  Gradle user home and evidence root. The token is passed to Gradle as a header only and
  is redacted from command/evidence files.
- `central` accepts no repository URL or credential and obtains the fork group from
  Maven Central only. It also requires an empty supplied Gradle home and evidence root.

In all modes `io.github.leminity.realm` is routed to exactly one fork repository in both
buildscript/plugin and dependency resolution. Google, the external Maven Central entry,
and the plugin portal explicitly exclude the fork group. JitPack and Maven Local are never
configured. Remote modes remove the fork build's offline flag only inside the isolated
home; the immutable official lane remains its established offline Gradle 7.5 lane.

For a no-device command/routing check, use `--dry-run` with an explicit identity tuple;
it rejects any SDK below 37, page size other than 16384, AVD substitution, or incompatible
16 KiB properties before it can invoke adb. A real run still performs every existing schema,
migration, wrong-key, notification, thread, restart, force-stop, no-network, and checksum
gate.
