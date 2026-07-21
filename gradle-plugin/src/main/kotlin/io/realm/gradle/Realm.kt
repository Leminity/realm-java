// Modified by Leminity from the upstream Realm Java project.
package io.realm.gradle

import com.android.build.api.dsl.CommonExtension
import io.realm.transformer.registerRealmTransformerTask
import org.gradle.api.GradleException
import org.gradle.api.Plugin
import org.gradle.api.Project
import org.gradle.api.artifacts.UnknownConfigurationException
import org.slf4j.Logger
import org.slf4j.LoggerFactory

val logger: Logger = LoggerFactory.getLogger("realm-logger")

const val ANDROID_TEST_IMPLEMENTATION = "androidTestImplementation"

private const val ANDROID_APPLICATION_PLUGIN_ID = "com.android.application"
private const val ANDROID_LIBRARY_PLUGIN_ID = "com.android.library"
private const val LEGACY_KAPT_PLUGIN_ID = "com.android.legacy-kapt"
private const val FORK_GROUP = "io.github.leminity.realm"

// TODO Run a Task or Visitor to collect runtimeClassPath, then serialize it
//      Run another task that depends on the output of the first task in order to deserialize the ClassPool and process each class apart
open class Realm : Plugin<Project> {
    override fun apply(project: Project) {
        var configured = false
        val configureOnce = {
            if (!configured) {
                configured = true
                configureAndroidProject(project)
            }
        }

        // These callbacks also cover consumers that apply realm-android before the Android plugin.
        project.pluginManager.withPlugin(ANDROID_APPLICATION_PLUGIN_ID) { configureOnce() }
        project.pluginManager.withPlugin(ANDROID_LIBRARY_PLUGIN_ID) { configureOnce() }

        project.afterEvaluate {
            if (!configured) {
                throw GradleException("'$ANDROID_APPLICATION_PLUGIN_ID' or '$ANDROID_LIBRARY_PLUGIN_ID' plugin required.")
            }
        }
    }

    private fun configureAndroidProject(project: Project) {
        checkCompatibleAGPVersion()

        val dependencyConfigurationName = getDependencyConfigurationName(project)
        val extension = project.extensions.create("realm", RealmPluginExtension::class.java)
        val hasKotlinSources = usesKotlinSources(project)
        extension.isKotlinExtensionsEnabled = hasKotlinSources

        // AGP 9 finalizes Kotlin processor wiring before afterEvaluate. Apply the legacy KAPT
        // bridge while the Android plugin is being configured; processor dependencies remain
        // selected after evaluation so Java-only projects keep annotationProcessor semantics.
        if (hasKotlinSources) {
            project.pluginManager.apply(LEGACY_KAPT_PLUGIN_ID)
        }

        registerRealmTransformerTask(project)
        project.dependencies.add(
            dependencyConfigurationName,
            forkCoordinate("realm-annotations")
        )

        project.afterEvaluate {
            val isKotlinProject = usesKotlinSources(project)

            if (extension.isSyncEnabled) {
                throw GradleException(
                    "Realm Sync/ObjectServer is unsupported by this fork. " +
                        "Set realm { syncEnabled = false } to use the local database artifacts."
                )
            }

            if (isKotlinProject) {
                configureKapt(project)
            } else {
                configureJavaAnnotationProcessor(project)
            }

            // FIXME When injected, dependencies are not propagating correctly from the main release to the
            // android test releases. We solve it by injecting them into the instrumented tests manually.
            listOf(
                dependencyConfigurationName,
                ANDROID_TEST_IMPLEMENTATION
            ).forEach { configurationName ->
                setDependencies(project, configurationName, extension.isKotlinExtensionsEnabled)
            }
        }
    }

    private fun configureKapt(project: Project) {
        var dependenciesAdded = false
        project.pluginManager.withPlugin(LEGACY_KAPT_PLUGIN_ID) {
            if (!dependenciesAdded) {
                dependenciesAdded = true
                project.dependencies.add("kapt", forkCoordinate("realm-annotations-processor"))
                project.dependencies.add("kaptAndroidTest", forkCoordinate("realm-annotations-processor"))
            }
        }

    }

    private fun configureJavaAnnotationProcessor(project: Project) {
        check(project.configurations.findByName("annotationProcessor") != null) {
            "Android annotationProcessor configuration is required for Java Realm models."
        }
        project.dependencies.add("annotationProcessor", forkCoordinate("realm-annotations-processor"))
        project.dependencies.add("androidTestAnnotationProcessor", forkCoordinate("realm-annotations-processor"))
    }

    private fun usesKotlinSources(project: Project): Boolean {
        val android = project.extensions.getByType(CommonExtension::class.java)
        if (!android.enableKotlin) {
            return false
        }

        // AGP 9 enables its built-in Kotlin support by default. Keep Java-only projects on the
        // annotationProcessor path by selecting KAPT only when a public Android source set has Kotlin code.
        return android.sourceSets.any { sourceSet ->
            (sourceSet.java.directories + sourceSet.kotlin.directories).any { directory ->
                project.file(directory).walkTopDown().any { source ->
                    source.isFile && source.extension == "kt"
                }
            }
        }
    }

    companion object {

        private fun checkCompatibleAGPVersion() {
            val version = SimpleAGPVersion.ANDROID_GRADLE_PLUGIN_VERSION
            return when {
                version >= SimpleAGPVersion(7, 4) -> {
                    // minimum version compatible with https://developer.android.com/studio/releases/gradle-plugin-api-updates#support_for_transformations_based_on_whole_program_analysis
                    logger.debug("Realm Plugin used with AGP version: ${version.major}.${version.minor}.")
                }
                else -> {
                    throw GradleException("Android Gradle Plugin $version is not supported. Upgrade to Realm Java `10.15.0` or later.")
                }
            }
        }

        private fun getDependencyConfigurationName(project: Project): String {
            /*
             * Dependency configuration name for android gradle plugin 3.0.0-*.
             * We need to use 'api' instead of 'implementation' since user's model class
             * might be using Realm's classes and annotations.
             */
            val newDependencyName = "api"
            val oldDependencyName = "compile"
            return try {
                project.configurations.getByName(newDependencyName)
                newDependencyName
            } catch (ignored: UnknownConfigurationException) {
                oldDependencyName
            }
        }

        // This will setup the required dependencies.
        // This must only be called once, as removal of dependencies through the iterator API will
        // not propagate correctly into the IterationOrderRetainingSetElementSource which is backing
        // the dependency set deep inside the DefaultDependencySet implementation, and failure to do
        // so causes some internal caching in IterationOrderRetainingSetElementSource to skip
        // re-adding it if it had already been there once.
        private fun setDependencies(
            project: Project,
            dependencyConfigurationName: String,
            kotlinExtensionsEnabled: Boolean
        ) {
            // remove libraries first
            val iterator =
                project.configurations.getByName(dependencyConfigurationName).dependencies.iterator()
            while (iterator.hasNext()) {
                val item = iterator.next()
                if (item.group == FORK_GROUP || item.group == "io.realm") {
                    if (item.name.startsWith("realm-android-library")) {
                        iterator.remove()
                    }
                    if (item.name.startsWith("realm-android-kotlin-extensions")) {
                        iterator.remove()
                    }
                }
            }

            project.dependencies.add(
                dependencyConfigurationName,
                forkCoordinate("realm-android-library")
            )

            if (kotlinExtensionsEnabled) {
                project.dependencies.add(
                    dependencyConfigurationName,
                    forkCoordinate("realm-android-kotlin-extensions")
                )
            }
        }

        private fun forkCoordinate(artifact: String) = "$FORK_GROUP:$artifact:${Version.VERSION}"
    }
}
