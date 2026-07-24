# Realm Java — Leminity maintenance fork

[![Maven Central](https://img.shields.io/maven-central/v/io.github.leminity.realm/realm-gradle-plugin?colorB=4dc427&label=Maven%20Central)](https://central.sonatype.com/artifact/io.github.leminity.realm/realm-gradle-plugin)
[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://github.com/Leminity/realm-java/blob/agp9.1/LICENSE)

> **Modification notice:** Modified by Leminity from the upstream Realm Java project.

This repository is the **unofficial Leminity maintenance fork** of Realm Java for the
base local Android database. It is not the MongoDB-maintained upstream repository and
does not claim MongoDB endorsement or trademark rights.

## AGP 9.1 maintenance release

This branch maintains the **base local Realm database** from upstream Realm Java `v10.19.0`
for current Android builds. It replaces the legacy `BaseExtension`/AGP-internal integration that
fails under AGP 9 while keeping source changes limited to build compatibility. This is an
unofficial maintenance fork; it is not a new upstream Realm release.

### Supported and verified boundary

| Item | Supported or verified value |
| --- | --- |
| Fork version | `10.19.0-agp9.2` |
| Android Gradle Plugin | `9.1.1` |
| Gradle wrapper | `9.6.1` |
| Build JDK | JDK 17 |
| Android SDK | `compileSdk = 37`, `targetSdk = 37` (Android 17 / API 37) |
| Minimum Android version | `minSdk = 21` (Android 5.0) |
| Native toolchain | NDK `29.0.14206865`, CMake `3.27.7` |
| Kotlin | AGP 9 built-in Kotlin; fork internals/processors built with Kotlin `2.2.10` |
| Android modules | Application and library modules; Java-only, Kotlin-only, and mixed sources |
| Gradle behavior | Configuration cache supported by the verified fork build and consumer fixtures |
| Native ABIs | Exactly `armeabi-v7a`, `arm64-v8a`, and `x86_64`; **no `x86`** |
| Runtime validation | API 37 with 16 KiB page size, including native ELF/page-size checks |

`minSdk = 21` is the supported installation boundary. API 37 / Android 17 is the specifically
validated runtime target; do not interpret that validation as a claim that every intervening
OS/device combination was exhaustively tested.

### R8 consumer-rule correction

`10.19.0-agp9.2` fixes an R8 ownership gap in the Realm AAR consumer metadata. Realm discovers
classes annotated with `@RealmModule` through reflection, but the previous consumer rule did not
retain their constructors. The Realm AAR now owns the exact constructor keep rule required by
that behavior. Applications upgrading to `.2` should remove an equivalent application-local
workaround; no broad `io.realm` keep rule is required.

Only the local database is supported. Atlas Device Sync, ObjectServer, server-backed sessions,
and their related build variants are excluded. Keep Sync explicitly disabled:

```groovy
realm {
    syncEnabled = false
}
```

### Maven Central artifacts

Use group `io.github.leminity.realm` and version `10.19.0-agp9.2`. The release contains exactly
these six artifacts:

- `realm-gradle-plugin`
- `realm-transformer`
- `realm-annotations`
- `realm-annotations-processor`
- `realm-android-library`
- `realm-android-kotlin-extensions`

The `realm-android` Gradle plugin adds the matching fork library, annotations, annotation
processor (KAPT for Kotlin sources or `annotationProcessor` for Java sources), and Kotlin
extensions when Kotlin sources are present. **Do not also declare upstream
`io.realm:realm-*` dependencies**, and normally do not declare the fork runtime artifacts by
hand; the plugin keeps their versions and group consistent.

### Project setup (Groovy DSL)

#### 1. Repositories

In `settings.gradle`, make Google and Maven Central available to dependencies. The
`pluginManagement` block is optional when the project declares AGP through `buildscript`; it is
needed only when Android plugins are resolved through the `plugins { ... }` DSL.

When used, `pluginManagement` must be the first executable block in `settings.gradle`. If the
file also has a settings-level `plugins { ... }` block, keep that block immediately after
`pluginManagement` and before `dependencyResolutionManagement`, `rootProject.name`, `include`,
or any other statement:

```groovy
// Optional for buildscript-based projects. When present, this must be the first block.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

// If settings.gradle already contains plugins { ... }, keep it here.
// plugins { ... }

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = 'your-project'
include ':app'
```

#### 2. Root build file

When AGP is declared with the plugins DSL, keep Realm on the buildscript classpath because the
consumer plugin id is the legacy `realm-android` id:

```groovy
buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath 'io.github.leminity.realm:realm-gradle-plugin:10.19.0-agp9.2'
    }
}

plugins {
    id 'com.android.application' version '9.1.1' apply false
    id 'com.android.library' version '9.1.1' apply false
}
```

A classic root `build.gradle` is also supported:

```groovy
buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath 'com.android.tools.build:gradle:9.1.1'
        classpath 'io.github.leminity.realm:realm-gradle-plugin:10.19.0-agp9.2'
    }
}
```

Use only one AGP declaration style in a project.

#### 3. Gradle wrapper

Set `gradle/wrapper/gradle-wrapper.properties` to Gradle 9.6.1:

```properties
distributionUrl=https\://services.gradle.org/distributions/gradle-9.6.1-bin.zip
```

#### 4. App or library module

Apply the Android plugin first and then `realm-android`. For an application module:

```groovy
plugins {
    id 'com.android.application'
}

apply plugin: 'realm-android'

android {
    namespace 'com.example.app'
    compileSdk 37

    defaultConfig {
        applicationId 'com.example.app'
        minSdk 21
        targetSdk 37

        // Optional: constrain packaging to the three published ABIs.
        ndk {
            abiFilters 'armeabi-v7a', 'arm64-v8a', 'x86_64'
        }
    }
}

realm {
    syncEnabled = false
}
```

For an Android library, replace `com.android.application` with `com.android.library` and omit
`applicationId`; keep `namespace`, `compileSdk`, `minSdk`, and the Realm configuration. AGP 9's
built-in Kotlin support is used, so do not add the legacy `org.jetbrains.kotlin.android` plugin
merely to enable Kotlin in an Android module.

### Kotlin DSL differences

The repositories and wrapper values are the same. In a root `build.gradle.kts`:

```kotlin
buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath("io.github.leminity.realm:realm-gradle-plugin:10.19.0-agp9.2")
    }
}

plugins {
    id("com.android.application") version "9.1.1" apply false
    id("com.android.library") version "9.1.1" apply false
}
```

In an application module `build.gradle.kts`:

```kotlin
plugins {
    id("com.android.application")
}

apply(plugin = "realm-android")

android {
    namespace = "com.example.app"
    compileSdk = 37
    defaultConfig {
        applicationId = "com.example.app"
        minSdk = 21
        targetSdk = 37
        ndk {
            abiFilters += setOf("armeabi-v7a", "arm64-v8a", "x86_64")
        }
    }
}

extensions.configure(io.realm.gradle.RealmPluginExtension::class.java) {
    setSyncEnabled(false)
}
```

For `settings.gradle.kts`, use `id("...")`/`url = uri(...)` Kotlin syntax as usual; the required
repositories remain `google()`, `mavenCentral()`, and `gradlePluginPortal()` under
`pluginManagement`, with `google()` and `mavenCentral()` under
`dependencyResolutionManagement`.

### Migrating from official Realm Java 10.19.0

1. Replace only the plugin classpath coordinate:
   `io.realm:realm-gradle-plugin:10.19.0` →
   `io.github.leminity.realm:realm-gradle-plugin:10.19.0-agp9.2`.
2. Remove explicit `io.realm:realm-android-library`, `realm-annotations`, processors, or Kotlin
   extensions. Let `realm-android` inject the fork artifacts.
3. Keep `apply plugin: 'realm-android'` and add `realm { syncEnabled = false }`.
4. Set AGP 9.1.1, Gradle 9.6.1, JDK 17, SDK 37, and `minSdk 21` as shown above.
5. Remove `x86` from ABI filters. Use an **x86_64** emulator for desktop Android testing.
6. Keep the existing `io.realm.*` model and database API calls. The fork was compatibility-tested
   against the 10.19.0 public API and local Realm file fixtures, including encrypted and
   bidirectional file cases; the guarantee does not extend to excluded Sync/ObjectServer APIs.
7. If upgrading from `10.19.0-agp9.1`, remove any application-local copy of the
   `@RealmModule` constructor keep rule after resolving `.2`; the rule is packaged by the Realm
   AAR.
8. Back up production Realm files before any SDK migration and run application-specific schema,
   migration, encryption, and rollback tests on representative copies.

### Troubleshooting and verification

After changing coordinates, clear stale daemons and cached resolution, then rebuild:

```bash
./gradlew --stop
./gradlew --no-daemon --refresh-dependencies clean assemble
```

If resolution still references `io.realm`, inspect the app classpaths:

```bash
./gradlew :app:dependencyInsight \
  --configuration debugRuntimeClasspath \
  --dependency io.github.leminity.realm
./gradlew :app:dependencies --configuration debugRuntimeClasspath
```

The resolved Realm modules must use `io.github.leminity.realm:...:10.19.0-agp9.2`; no upstream
`io.realm:realm-*` module should remain. Also run the relevant unit/instrumentation suites on an
API 37 x86_64 emulator or device before rollout.

The `G011_OFFICIAL_GRADLE_75` value that may appear in release evidence is **oracle-only**: Gradle
7.5 runs the unmodified official 10.19.0 fixture to produce compatibility inputs. It is never the
fork build or consumer toolchain, which remains AGP 9.1.1 with Gradle 9.6.1.

### Release immutability and further documentation

Tag `v10.19.0-agp9.2` is the release-candidate tag input. It must be created only after the exact
candidate commit, Realm Core source, test results, and artifact hashes are sealed; after creation
it must never move. The predecessor `v10.19.0-agp9.1` tag and its published artifacts remain
immutable.

See the detailed [fork and release contract](docs/release/G010-fork-release.md) and the
release record for provenance, artifact boundaries, and reproducible verification notes.

## Fork release contract

This is an **unofficial Leminity maintenance fork** of upstream Realm Java. The reproducible
fork/release contract, provenance, compatibility boundaries, and local-only verification
commands are documented in [`docs/release/G010-fork-release.md`](docs/release/G010-fork-release.md).
The fork is versioned as `10.19.0-agp9.2`; tag `v10.19.0-agp9.2` is its sealed tag input.
It descends from upstream tag `v10.19.0`. Historical integration milestone: `0e8bddf0a46827a7336a6a13406df8e35834db25`.
Its current canonical Realm Core provenance is
`a5b7ed7bb8f0db4d362c7e45b2f38358a4aeab47` (including historical behavior backport `d7b52ccb`).

The supported surface is the base local database only. Sync and ObjectServer integrations are
unsupported and excluded from this fork's release contract. The published coordinates use the
`io.github.leminity.realm` group; the upstream `io.realm` coordinates are not this fork.

## Upstream project context

Realm is a mobile database that runs directly inside phones, tablets, or wearables. This fork
retains upstream Realm Java history and documentation where useful, but the fork identity and
release contract above govern this repository.

## Realm Kotlin

The [Realm Kotlin SDK](https://github.com/realm/realm-kotlin) is now GA and can be used for both Android and Kotlin Multiplatform. While we are still adding features, please consider using Realm Kotlin for any new project, and let us know if you miss anything there!

## Features

* **Mobile-first:** Realm is the first database built from the ground up to run directly inside phones, tablets, and wearables.
* **Simple:** Data is directly exposed as objects and queryable by code, removing the need for ORM's riddled with performance & maintenance issues. Plus, we've worked hard to [keep our API down to very few classes](https://www.mongodb.com/docs/atlas/device-sdks/sdk/java/): most of our users pick it up intuitively, getting simple apps up & running in minutes.
* **Modern:** Realm supports easy thread-safety, relationships & encryption.
* **Fast:** Realm is faster than even raw SQLite on common operations while maintaining an extremely rich feature set.
* **[Device Sync](https://www.mongodb.com/atlas/app-services/device-sync)**: Makes it simple to keep data in sync across users, devices, and your backend in real-time. Get started for free with [a template application](https://github.com/mongodb/template-app-react-native-todo) and [create the cloud backend](http://mongodb.com/realm/register?utm_medium=github_atlas_CTA&utm_source=realm_js_github).

## Getting Started

Please see the [detailed instructions in our docs](https://www.mongodb.com/docs/atlas/device-sdks/sdk/java/install/) to add Realm to your project.

## Documentation

Documentation for Realm can be found at [mongodb.com/docs/atlas/device-sdks/sdk/java/](https://www.mongodb.com/docs/atlas/device-sdks/sdk/java/).
The API reference is located at [mongodb.com/docs/atlas/device-sdks/sdk/java/api/](https://www.mongodb.com/docs/atlas/device-sdks/sdk/java/api/).

## Getting Help

- **Got a question?**: Look for previous questions on the [#realm tag](https://stackoverflow.com/questions/tagged/realm?sort=newest) — or [ask a new question](http://stackoverflow.com/questions/ask?tags=realm). We actively monitor & answer questions on StackOverflow! You can also check out our [Community Forum](https://developer.mongodb.com/community/forums/tags/c/realm/9/realm-sdk) where general questions about how to do something can be discussed.
- **Think you found a fork bug?** [Open an issue](https://github.com/Leminity/realm-java/issues/new). If possible, include the fork version, a full log, the Realm file, and a project that shows the issue.
- **Have a fork feature request?** [Open an issue](https://github.com/Leminity/realm-java/issues/new). Tell us what the feature should do and why you want the feature.

## Using Snapshots

If you want to test recent bugfixes or features that have not been packaged in an official release yet, you can use a **-SNAPSHOT** release of the current development version of Realm via Gradle, available on [Sonatype OSS](https://oss.sonatype.org/#nexus-search;quick~realm-gradle-plugin)


```
buildscript {
    repositories {
        mavenCentral()
        google()
        maven {
            url 'https://oss.sonatype.org/content/repositories/snapshots/'
        }
        jcenter()
    }
    dependencies {
        classpath "io.realm:realm-gradle-plugin:<version>-SNAPSHOT"
    }
}

allprojects {
    repositories {
        mavenCentral()
        google()
        maven {
            url 'https://oss.sonatype.org/content/repositories/snapshots/'
        }
        jcenter()
    }
}
```

See [version.txt](version.txt) for the latest version number.

## Building Realm

In case you don't want to use the precompiled version, you can build Realm yourself from source.

### Prerequisites

 * Download the [**JDK 8**](http://www.oracle.com/technetwork/java/javase/downloads/jdk8-downloads-2133151.html) from Oracle and install it.
 * The latest stable version of Android Studio. Currently [4.1.1](https://developer.android.com/studio/).
 * Download & install the Android SDK **Build-Tools 29.0.3**, **Android Pie (API 29)** (for example through Android Studio’s **Android SDK Manager**).
 * Install CMake version 3.18.4 and build Ninja.
 * Install the NDK (Side-by-side) **21.0.6113669** from the SDK Manager in Android Studio. Remember to check `☑  Show package details` in the manager to display all available versions.

 * Add the Android home environment variable to your profile:

    ```
    export ANDROID_HOME=~/Library/Android/sdk
    ```

 * If you are launching Android Studio from the macOS Finder, you should also run the following command:

    ```
    launchctl setenv ANDROID_HOME "$ANDROID_HOME"
    ```

 * If you'd like to specify the location in which to store the archives of Realm Core, define the `REALM_CORE_DOWNLOAD_DIR` environment variable. It enables caching core release artifacts.

   ```
   export REALM_CORE_DOWNLOAD_DIR=~/.realmCore
   ```

   macOS users must also run the following command for Android Studio to see this environment variable.

   ```
   launchctl setenv REALM_CORE_DOWNLOAD_DIR "$REALM_CORE_DOWNLOAD_DIR"
   ```

It would be a good idea to add all of the symbol definitions (and their accompanying `launchctl` commands, if you are using macOS) to your `~/.profile` (or `~/.zprofile` if the login shell is `zsh`)

 * If you develop Realm Java with Android Studio, we recommend you to exclude some directories from indexing target by executing following steps on Android Studio. It really speeds up indexing phase after the build.

    - Under `/realm/realm-library/`, select `build`, `.cxx` and `distribution` folders in `Project` view.
    - Press `Command + Shift + A` to open `Find action` dialog. If you are not using default keymap nor using macOS, you can find your shortcut key in `Keymap` preference by searching `Find action`.
    - Search `Excluded` (not `Exclude`) action and select it. Selected folder icons should become orange (in default theme).
    - Restart Android Studio.

### Download sources

You can download the source code of Realm Java by using git. Since realm-java has git submodules, use `--recursive` when cloning the repository.

```
git clone git@github.com:Leminity/realm-java.git --recursive
```

or

```
git clone https://github.com/Leminity/realm-java.git --recursive
```

### Build

Once you have completed all the pre-requisites building Realm is done with a simple command.

```
./gradlew assemble
```

That command will generate:

 * a jar file for the Realm Gradle plugin
 * an aar file for the Realm library
 * a jar file for the annotations
 * a jar file for the annotations processor

The full build may take an hour or more, to complete.

### Building from source

It is possible to build Realm Java with the submodule version of Realm Core. This is done by providing the following parameter when building: `-PbuildCore=true`.

```
./gradlew assembleBase -PbuildCore=true
```

You can turn off interprocedural optimizations with the following parameter: `-PenableLTO=false`. 

```
./gradlew assembleBase -PenableLTO=false`
```

Note: Building the `Base` variant would always build realm-core.

Note: Interprocedural optimizations are enabled by default.

Note: If you want to build from source inside Android Studio, you need to update the Gradle parameters by going into the Realm projects settings `Settings > Build, Execution, Deployment > Compiler > Command-line options` and add `-PbuildCore=true` or `-PenableLTO=false` to it. Alternatively you can add it into your `gradle.properties`:

```
buildCore=true
enableLTO=false
```

Note: If building on OSX you might like to prevent Gatekeeper to block all NDK executables by disabling it: `sudo spctl --master-disable`. Remember to enable it afterwards: `sudo spctl --master-enable`

### Other Commands

 * `./gradlew tasks` will show all the available tasks
 * `./gradlew javadoc` will generate the Javadocs
 * `./gradlew monkeyExamples` will run the monkey tests on all the examples
 * `./gradlew installRealmJava` will install the Realm library and plugin to mavenLocal()
 * `./gradlew clean -PdontCleanJniFiles` will remove all generated files except for JNI related files. This reduces recompilation time a lot.
 * `./gradlew connectedUnitTests -PbuildTargetABIs=$(adb shell getprop ro.product.cpu.abi)` will build JNI files only for the ABI which corresponds to the connected device.  These tests require a running Object Server (see below)

Generating the Javadoc using the command above may generate warnings. The Javadoc is generated despite the warnings.


### Upgrading Gradle Wrappers

 All gradle projects in this repository have `wrapper` task to generate Gradle Wrappers. Those tasks refer to `gradle` property defined in `/dependencies.list` to determine Gradle Version of generating wrappers.
We have a script `./tools/update_gradle_wrapper.sh` to automate these steps. When you update Gradle Wrappers, please obey the following steps.

 1. Edit `gradle` property in defined in `/dependencies.list` to new Gradle Wrapper version.
 2. Execute `/tools/update_gradle_wrapper.sh`.

### Gotchas

The repository is organized into six Gradle projects:

 * `realm`: it contains the actual library (including the JNI layer) and the annotations processor.
 * `realm-annotations`: it contains the annotations defined by Realm.
 * `realm-transformer`: it contains the bytecode transformer.
 * `gradle-plugin`: it contains the Gradle plugin.
 * `examples`: it contains the example projects. This project directly depends on `gradle-plugin` which adds a dependency to the artifacts produced by `realm`.
 * The root folder is another Gradle project.  All it does is orchestrate the other jobs.

This means that `./gradlew clean` and `./gradlew cleanExamples` will fail if `assembleExamples` has not been executed first.
Note that IntelliJ [does not support multiple projects in the same window](https://youtrack.jetbrains.com/issue/IDEABKL-6118#)
so each of the six Gradle projects must be imported as a separate IntelliJ project.

Since the repository contains several completely independent Gradle projects, several independent builds are run to assemble it.
Seeing a line like: `:realm:realm-library:compileBaseDebugAndroidTestSources UP-TO-DATE` in the build log does *not* imply
that you can run `./gradlew :realm:realm-library:compileBaseDebugAndroidTestSources`.

## Examples

The `./examples` folder contains many example projects showing how Realm can be used. If this is the first time you checkout or pull a new version of this repository to try the examples, you must call `./gradlew installRealmJava` from the top-level directory first. Otherwise, the examples will not compile as they depend on all Realm artifacts being installed in `mavenLocal()`.

Standalone examples can be [downloaded from website](https://www.mongodb.com/docs/realm/sdk/java/quick-starts/quick-start-local/#complete-example).

## Running Tests on a Device

To run these tests, you must have a device connected to the build computer, and the `adb` command must be in your `PATH`

1. Connect an Android device and verify that the command `adb devices` shows a connected device:

    ```sh
    adb devices
    List of devices attached
    004c03eb5615429f device
    ```

2. Run instrumentation tests:

    ```sh
    cd realm
    ./gradlew connectedBaseDebugAndroidTest
    ```

These tests may take as much as half an hour to complete.

## Running Tests Using The Realm Object Server

Tests in `realm/realm-library/src/syncIntegrationTest` require a running testing server to work.
A docker image can be built from `tools/sync_test_server/Dockerfile` to run the test server.
`tools/sync_test_server/start_server.sh` will build the docker image automatically.

To run a testing server locally:

1. Install [docker](https://www.docker.com/products/overview) and run it.

2. Run `tools/sync_test_server/start_server.sh`:

    ```sh
    cd tools/sync_test_server
    ./start_server.sh
    ```

    This command will not complete until the server has stopped.

3. Run instrumentation tests

    In a new terminal window, run:

    ```sh
    cd realm
    ./gradlew connectedObjectServerDebugAndroidTest
    ```

Note that if using VirtualBox (Genymotion), the network needs to be bridged for the tests to work.
This is done in `VirtualBox > Network`. Set "Adapter 2" to "Bridged Adapter".

These tests may take as much as half an hour to complete.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for more details!

This project adheres to the [MongoDB Code of Conduct](https://www.mongodb.com/community-code-of-conduct).
By participating, you are expected to uphold this code. Please report
unacceptable behavior to [community-conduct@mongodb.com](mailto:community-conduct@mongodb.com).

The directory `realm/config/studio` contains lint and style files recommended for project code.
Import them from Android Studio with Android Studio > Preferences... > Code Style > Manage... > Import,
or Android Studio > Preferences... > Inspections > Manage... > Import.  Once imported select the
style/lint in the drop-down to the left of the Manage... button.

## License

Realm Java is published under the Apache 2.0 license.

Realm Core is also published under the Apache 2.0 license and is available
[here](https://github.com/realm/realm-core).

## Feedback

**_If you use Realm and are happy with it, all we ask is that you, please consider sending out a tweet mentioning [@realm](http://twitter.com/realm) to share your thoughts!_**

**_And if you don't like it, please let us know what you would like improved, so we can fix it!_**

<img style="width: 0px; height: 0px;" src="https://3eaz4mshcd.execute-api.us-east-1.amazonaws.com/prod?s=https://github.com/realm/realm-java#README.md">
