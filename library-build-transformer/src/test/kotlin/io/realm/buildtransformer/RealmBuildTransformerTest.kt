/*
 * Copyright 2026 Leminity
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

import io.realm.buildtransformer.testclasses.SimpleTestClass
import io.realm.buildtransformer.testclasses.SimpleTestFields
import io.realm.buildtransformer.testclasses.SimpleTestMethods
import org.gradle.api.file.Directory
import org.gradle.api.file.RegularFile
import org.gradle.testfixtures.ProjectBuilder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.security.MessageDigest
import java.util.jar.JarEntry
import java.util.jar.JarFile
import java.util.jar.JarOutputStream

class RealmBuildTransformerTest {

    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun directoryOnlyInputRetainsResourcesAndStripsAnnotatedSymbols() {
        val classes = temporaryFolder.newFolder("directory-input")
        copyClass(SimpleTestClass::class.java, classes)
        copyClass(SimpleTestFields::class.java, classes)
        copyClass(SimpleTestMethods::class.java, classes)
        File(classes, "META-INF/test-resource.txt").apply {
            parentFile.mkdirs()
            writeText("directory resource")
        }

        val output = transform(emptyList(), listOf(classes), "directory-only.jar")

        assertTrue(entries(output).contains("META-INF/test-resource.txt"))
        assertFalse(entries(output).contains(classEntry(SimpleTestClass::class.java)))

        val transformedClasses = extractClasses(output)
        val loader = DynamicClassLoader(javaClass.classLoader)
        val fields = loader.loadClass(SimpleTestFields::class.java.name, transformedClasses)
        val methods = loader.loadClass(SimpleTestMethods::class.java.name, transformedClasses)
        assertNotNull(fields.getField("field2"))
        assertFieldMissing(fields, "field1")
        assertNotNull(methods.getMethod("bar"))
        assertMethodMissing(methods, "foo")
    }

    @Test
    fun mixedJarAndDirectoryInputsRetainUniqueEntries() {
        val directory = temporaryFolder.newFolder("mixed-directory")
        copyClass(SimpleTestFields::class.java, directory)
        File(directory, "directory-resource.txt").writeText("directory")

        val jar = temporaryFolder.newFile("mixed.jar")
        writeJar(jar, mapOf(
            classEntry(SimpleTestMethods::class.java) to classBytes(SimpleTestMethods::class.java),
            "jar-resource.txt" to "jar".toByteArray(),
        ))

        val output = transform(listOf(jar), listOf(directory), "mixed-output.jar")
        val outputEntries = entries(output)
        assertTrue(outputEntries.contains(classEntry(SimpleTestFields::class.java)))
        assertTrue(outputEntries.contains(classEntry(SimpleTestMethods::class.java)))
        assertTrue(outputEntries.contains("directory-resource.txt"))
        assertTrue(outputEntries.contains("jar-resource.txt"))
    }

    @Test
    fun duplicateEntriesAreRejectedWithoutReplacingExistingOutput() {
        val directory = temporaryFolder.newFolder("duplicate-directory")
        File(directory, "duplicate-resource.txt").writeText("directory")
        val jar = temporaryFolder.newFile("duplicate.jar")
        writeJar(jar, mapOf("duplicate-resource.txt" to "jar".toByteArray()))
        val output = temporaryFolder.newFile("duplicate-output.jar")
        writeJar(output, mapOf("previous-output.txt" to "preserve".toByteArray()))

        try {
            transform(listOf(jar), listOf(directory), output)
            throw AssertionError("Expected duplicate inputs to be rejected")
        } catch (_: IllegalArgumentException) {
            assertEquals(setOf("previous-output.txt"), entries(output))
        }
    }

    @Test
    fun equivalentInputsProduceIdenticalOutput() {
        val directory = temporaryFolder.newFolder("repeatable-directory")
        copyClass(SimpleTestFields::class.java, directory)
        File(directory, "repeatable-resource.txt").writeText("repeatable")

        val first = transform(emptyList(), listOf(directory), "first.jar")
        val second = transform(emptyList(), listOf(directory), "second.jar")

        assertEquals(sha256(first), sha256(second))
    }

    private fun transform(jars: List<File>, directories: List<File>, outputName: String): File {
        return transform(jars, directories, temporaryFolder.newFile(outputName))
    }

    private fun transform(jars: List<File>, directories: List<File>, output: File): File {
        val project = ProjectBuilder.builder()
            .withProjectDir(temporaryFolder.newFolder("project-${output.name}"))
            .build()
        val task = project.tasks.create("transform", ModifyClassesTask::class.java)
        task.annotationQualifiedName.set("io.realm.internal.annotations.ObjectServer")
        task.allJars.set(jars.map { regularFile(project, it) })
        task.allDirectories.set(directories.map { directory(project, it) })
        task.output.set(regularFile(project, output))
        task.taskAction()
        return output
    }

    private fun regularFile(project: org.gradle.api.Project, file: File): RegularFile {
        return project.layout.file(project.provider { file }).get()
    }

    private fun directory(project: org.gradle.api.Project, file: File): Directory {
        return project.layout.dir(project.provider { file }).get()
    }

    private fun entries(jar: File): Set<String> = JarFile(jar).use { archive ->
        archive.entries().toList().map { it.name }.toSet()
    }

    private fun extractClasses(jar: File): Set<File> {
        val classes = mutableSetOf<File>()
        val destination = temporaryFolder.newFolder("extracted")
        JarFile(jar).use { archive ->
            archive.entries().toList()
                .filter { !it.isDirectory && it.name.endsWith(".class") }
                .forEach { entry ->
                    val output = File(destination, entry.name)
                    output.parentFile.mkdirs()
                    archive.getInputStream(entry).use { input -> output.outputStream().use(input::copyTo) }
                    classes.add(output)
                }
        }
        return classes
    }

    private fun copyClass(clazz: Class<*>, destination: File) {
        val entry = classEntry(clazz)
        val output = File(destination, entry)
        output.parentFile.mkdirs()
        val input = requireNotNull(clazz.classLoader.getResourceAsStream(entry)) {
            "Missing test class resource: $entry"
        }
        input.use { output.outputStream().use(it::copyTo) }
    }

    private fun classBytes(clazz: Class<*>): ByteArray {
        val entry = classEntry(clazz)
        val input = requireNotNull(clazz.classLoader.getResourceAsStream(entry)) {
            "Missing test class resource: $entry"
        }
        return input.use { it.readBytes() }
    }

    private fun classEntry(clazz: Class<*>): String = "${clazz.name.replace('.', '/')}.class"

    private fun writeJar(output: File, entries: Map<String, ByteArray>) {
        JarOutputStream(FileOutputStream(output)).use { archive ->
            entries.forEach { (name, bytes) ->
                archive.putNextEntry(JarEntry(name))
                archive.write(bytes)
                archive.closeEntry()
            }
        }
    }

    private fun sha256(file: File): String = MessageDigest.getInstance("SHA-256")
        .digest(Files.readAllBytes(file.toPath()))
        .joinToString("") { "%02x".format(it) }

    private fun assertFieldMissing(clazz: Class<*>, field: String) {
        try {
            clazz.getField(field)
            throw AssertionError("Expected field $field to be missing")
        } catch (_: NoSuchMethodException) {
            throw AssertionError("Reflection lookup for field unexpectedly resolved as a method")
        } catch (_: NoSuchFieldException) {
            // Expected: the transformed class no longer contains this field.
        }
    }

    private fun assertMethodMissing(clazz: Class<*>, method: String) {
        try {
            clazz.getMethod(method)
            throw AssertionError("Expected method $method to be missing")
        } catch (_: NoSuchMethodException) {
            // Expected: the transformed class no longer contains this method.
        }
    }
}
