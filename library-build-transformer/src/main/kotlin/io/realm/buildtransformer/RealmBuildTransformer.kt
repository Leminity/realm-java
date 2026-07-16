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
package io.realm.buildtransformer

import com.android.build.api.variant.AndroidComponentsExtension
import io.realm.buildtransformer.asm.visitors.AnnotatedCodeStripVisitor
import io.realm.buildtransformer.util.Stopwatch
import org.gradle.api.DefaultTask
import org.gradle.api.Project
import org.gradle.api.file.Directory
import org.gradle.api.file.RegularFile
import org.gradle.api.file.RegularFileProperty
import org.gradle.api.provider.ListProperty
import org.gradle.api.provider.Property
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.InputFiles
import org.gradle.api.tasks.OutputFiles
import org.gradle.api.tasks.TaskAction
import org.objectweb.asm.ClassReader
import org.objectweb.asm.ClassWriter
import org.slf4j.Logger
import org.slf4j.LoggerFactory
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.nio.file.Files
import java.util.jar.JarEntry
import java.util.jar.JarFile
import java.util.jar.JarOutputStream

// Type aliases for improving readability
typealias ByteCodeTypeDescriptor = String
typealias QualifiedName = String
typealias ByteCodeMethodName = String
typealias FieldName = String

// Package level logger
val logger: Logger = LoggerFactory.getLogger("realm-build-logger")

/**
 * Transformer that will strip all classes, methods and fields annotated with a given annotation from
 * a specific Android flavour. It is also possible to provide a list of files to delete whether or
 * not they have the annotation. These files will only be deleted from the defined flavour.
 */
class RealmBuildTransformer(
    private val annotationQualifiedName: Property<String>,
    private val inputJars: ListProperty<RegularFile>,
    private val inputDirectories: ListProperty<Directory>,
    private val output: RegularFileProperty,
) {

    internal fun transform() {
        // The AGP build infrastructure will inject the task input and outputs and location is not
        // to be considered as part of the API, so we must be able to accept the current scenario
        // where the input and output is actually the same JAR. Thus, we write everything to a
        // temporary output to avoid truncating the input, and then write this temporary output
        // back to the final output location in the end.
        // See https://developer.android.com/reference/tools/gradle-api/7.4/com/android/build/api/variant/ScopedArtifactsOperation#toTransform(com.android.build.api.artifact.ScopedArtifact,kotlin.Function1,kotlin.Function1,kotlin.Function1)
        // for further information.
        val timer = Stopwatch()
        timer.start("Build Transform time")

        // The ASM infrastructure does not allow to inspect annotations of methods before visiting
        // them. This prevents inspecting and stripping methods in the same pass, thus we first
        // collect information about annotations and then secondly strip the annotation symbols.
        // 1. Collect annotation information
        val annotationDescriptor = createDescriptor(annotationQualifiedName.get())
        val metadataCollector =
            io.realm.buildtransformer.asm.visitors.AnnotationVisitor(annotationDescriptor)
        val entryNames = mutableSetOf<String>()
        forEachInputEntry { name, inputStream ->
            inputStream.use { stream ->
                require(entryNames.add(name)) { "Duplicate transformed entry: $name" }
                if (name.endsWith(".class")) {
                    val classReader = ClassReader(stream)
                    classReader.accept(metadataCollector, 0)
                }
            }
        }
        // 2. Strip annotated symbols
        val outputFile = output.get().asFile
        val temporaryOutput = File("${outputFile.absolutePath}.tmp")
        outputFile.parentFile?.mkdirs()
        temporaryOutput.delete()
        try {
            JarOutputStream(BufferedOutputStream(FileOutputStream(temporaryOutput))).use { outputProvider ->
                forEachInputEntry { name, inputStream ->
                    val bytes = inputStream.use { stream ->
                        if (name.endsWith(".class")) {
                            val writer =
                                ClassWriter(0) // We don't modify methods so no reason to re-calculate method frames
                            val classRemover = AnnotatedCodeStripVisitor(
                                annotationDescriptor,
                                metadataCollector.annotatedClasses,
                                metadataCollector.annotatedMethods,
                                metadataCollector.annotatedFields,
                                writer
                            )
                            ClassReader(stream).accept(classRemover, 0)
                            if (classRemover.deleteClass) ByteArray(0) else writer.toByteArray()
                        } else {
                            stream.readBytes()
                        }
                    }
                    if (bytes.isNotEmpty()) {
                        outputProvider.putNextEntry(JarEntry(name).apply { time = 0L })
                        outputProvider.write(bytes)
                        outputProvider.closeEntry()
                    }
                }
            }
            temporaryOutput.copyTo(outputFile, overwrite = true)
        } finally {
            temporaryOutput.delete()
        }
        timer.stop()
    }

    private fun forEachInputEntry(block: (name: String, inputStream: InputStream) -> Unit) {
        inputJars.get().sortedBy { it.asFile.absolutePath }.forEach { regularFile ->
            JarFile(regularFile.asFile).use { jarFile ->
                jarFile.entries().toList()
                    .filterNot { it.isDirectory }
                    .sortedBy { it.name }
                    .forEach { entry -> block(entry.name, jarFile.getInputStream(entry)) }
            }
        }
        inputDirectories.get().sortedBy { it.asFile.absolutePath }.forEach { directory ->
            val root = directory.asFile.toPath()
            val paths = Files.walk(root)
            try {
                paths.filter { Files.isRegularFile(it) }
                    .sorted()
                    .forEach { path ->
                        val name = root.relativize(path).toString().replace(File.separatorChar, '/')
                        block(name, Files.newInputStream(path))
                    }
            } finally {
                paths.close()
            }
        }
    }

    private fun createDescriptor(qualifiedName: String): String {
        return "L${qualifiedName.replace(".", "/")};"
    }

    companion object {
        fun register(project: Project, flavorToStrip: String, annotationQualifiedName: QualifiedName) {
            val androidComponents = project.extensions.getByType(AndroidComponentsExtension::class.java)
            androidComponents.onVariants { variant ->
                if (variant.name.startsWith(flavorToStrip)) {
                    val taskProvider = project.tasks.register(
                        "${variant.name}RealmBuildTransformer",
                        ModifyClassesTask::class.java
                    ) {
                        it.annotationQualifiedName.set(annotationQualifiedName)
                    }
                    variant.artifacts.forScope(com.android.build.api.variant.ScopedArtifacts.Scope.PROJECT)
                        .use<ModifyClassesTask>(taskProvider)
                        .toTransform(
                            com.android.build.api.artifact.ScopedArtifact.CLASSES,
                            ModifyClassesTask::allJars,
                            ModifyClassesTask::allDirectories,
                            ModifyClassesTask::output
                        )
                }
            }
        }
    }
}
abstract class ModifyClassesTask: DefaultTask() {
    @get:InputFiles
    abstract val allJars: ListProperty<RegularFile>

    @get:InputFiles
    abstract val allDirectories: ListProperty<Directory>

    @get:OutputFiles
    abstract val output: RegularFileProperty

    @get:Input
    abstract val annotationQualifiedName : Property<String>

    @TaskAction
    fun taskAction() {
        RealmBuildTransformer(annotationQualifiedName, allJars, allDirectories, output)
            .transform()
    }
}
