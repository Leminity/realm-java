// Modified by Leminity from the upstream Realm Java project.
/*
 * Copyright 2018 Realm Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package io.realm.transformer.ext

import com.android.build.api.dsl.ApplicationExtension
import com.android.build.api.dsl.LibraryExtension
import com.android.build.api.variant.AndroidComponentsExtension
import org.gradle.api.Project

/**
 * Attempts to determine the best possible unique AppId for this project.
 */
fun Project.getAppId(): String {
    // Use the Root project name, usually set in `settings.gradle`
    // This means that we don't treat apps with multiple flavours as different, nor
    // if a project contains more than one app (probably unlikely).
    // This seems acceptable. These cases would just show up as more builds for the
    // same AppId.
    return this.rootProject.name
}

/**
 * Returns the `targetSdk` property for this project if it is available.
 */
fun Project.getTargetSdk(): String {
    return extensions.findByType(ApplicationExtension::class.java)
        ?.defaultConfig
        ?.targetSdk
        ?.toString()
        ?: "unknown"
}

/**
 * Returns the `minSdk` property for this project if it is available.
 */
fun Project.getMinSdk(): String {
    return (extensions.findByType(ApplicationExtension::class.java)?.defaultConfig?.minSdk
        ?: extensions.findByType(LibraryExtension::class.java)?.defaultConfig?.minSdk)
        ?.toString()
        ?: "unknown"
}

/**
 * Returns the version of the Android Gradle Plugin that is used.
 */
fun Project.getAgpVersion(): String {
    return extensions.getByType(AndroidComponentsExtension::class.java).pluginVersion.toString()
}

fun Project.areIncrementalBuildsDisabled() =
    if(extensions.extraProperties.has("io.realm.disableIncrementalBuilds")){
        extensions.extraProperties["io.realm.disableIncrementalBuilds"] == "true"
    } else {
        false
    }

fun Project.targetType(): String = with(project.plugins) {
    when {
        findPlugin("com.android.application") != null -> "app"
        findPlugin("com.android.library") != null -> "library"
        else -> "unknown"
    }
}

fun Project.usesKotlin(): Boolean {
    return project.pluginManager.hasPlugin("kotlin-kapt")
}
