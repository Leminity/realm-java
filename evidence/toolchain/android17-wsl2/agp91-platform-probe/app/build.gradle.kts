plugins {
    id("com.android.application")
}

android {
    namespace = "io.realm.toolchainprobe"
    compileSdk = 37

    defaultConfig {
        applicationId = "io.realm.toolchainprobe"
        minSdk = 23
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"
    }
}

tasks.register("reportAndroidSdkResolution") {
    doLast {
        println("PROBE_COMPILE_SDK=${android.compileSdk}")
        println("PROBE_TARGET_SDK=${android.defaultConfig.targetSdk}")
    }
}
