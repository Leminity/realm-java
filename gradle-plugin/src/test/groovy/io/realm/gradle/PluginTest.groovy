/*
 * Copyright 2016 Realm Inc.
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

package io.realm.gradle

import org.gradle.testkit.runner.BuildResult
import org.gradle.testkit.runner.GradleRunner
import org.gradle.testkit.runner.TaskOutcome
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

import java.util.jar.JarOutputStream
import java.util.regex.Pattern
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

import static org.junit.Assert.assertEquals
import static org.junit.Assert.assertFalse
import static org.junit.Assert.assertNotNull
import static org.junit.Assert.assertTrue

/**
 * Black-box compatibility tests for the public {@code realm-android} plugin contract.
 *
 * The consumer fixtures deliberately use AGP's built-in Kotlin support. They must never
 * depend on deprecated AGP Transform APIs, ProjectBuilder internals, or reflection into
 * Gradle dependency handlers: all assertions come from a real Gradle invocation.
 */
@RunWith(Parameterized.class)
class PluginTest {

    private static final String AGP_VERSION = '9.1.1'
    private static final String FORK_GROUP = 'io.github.leminity.realm'
    private static final String FORK_VERSION = '10.19.0-agp9.1'

    @Parameterized.Parameters(name = '{0}-{1}-{2}')
    static Collection<Object[]> fixtures() {
        List<Object[]> result = []
        ['application', 'library'].each { androidPlugin ->
            ['java', 'kotlin', 'mixed'].each { language ->
                ['android-then-realm', 'realm-then-android'].each { order ->
                    result.add([androidPlugin, language, order] as Object[])
                }
            }
        }
        result
    }

    @Parameterized.Parameter(0)
    public String androidPlugin

    @Parameterized.Parameter(1)
    public String language

    @Parameterized.Parameter(2)
    public String order

    @Rule
    public final TemporaryFolder temporaryFolder = new TemporaryFolder()

    private File consumerProject
    private File moduleProject
    private File fixtureRepository

    @Before
    void setUp() {
        writeFixture(false)
    }

    @Test
    void pluginPreservesTheForkedAndroidContractAcrossTheCompatibilityMatrix() {
        BuildResult result = run(
            ':app:assembleDebug',
            ':app:assembleRelease',
            ':app:verifyRealmPluginContract',
            '--configuration-cache'
        ).build()

        assertTaskSucceeded(result, ':app:assembleDebug')
        assertTaskSucceeded(result, ':app:assembleRelease')
        assertTaskSucceeded(result, ':app:verifyRealmPluginContract')
        assertTaskSucceeded(result, ':app:debugRealmAccessorsTransformer')
        assertTaskSucceeded(result, ':app:releaseRealmAccessorsTransformer')

        assertConfigurationContains(result, 'api', 'realm-annotations')
        assertConfigurationContains(result, 'api', 'realm-android-library')
        assertConfigurationCount(result, 'api', language == 'java' ? 2 : 3)
        assertConfigurationContains(result, 'debugCompileClasspath', 'realm-annotations')
        assertConfigurationContains(result, 'debugCompileClasspath', 'realm-android-library')
        assertConfigurationContains(result, 'releaseCompileClasspath', 'realm-annotations')
        assertConfigurationContains(result, 'releaseCompileClasspath', 'realm-android-library')

        if (language == 'java') {
            assertConfigurationContains(result, 'annotationProcessor', 'realm-annotations-processor')
            assertConfigurationContains(result, 'androidTestAnnotationProcessor', 'realm-annotations-processor')
            assertFalse(result.output.contains('REALM-LEGACY-KAPT=true'))
        } else {
            assertConfigurationContains(result, 'api', 'realm-android-kotlin-extensions')
            assertConfigurationContains(result, 'kapt', 'realm-annotations-processor')
            assertConfigurationContains(result, 'kaptAndroidTest', 'realm-annotations-processor')
            assertTrue(result.output.contains('REALM-LEGACY-KAPT=true'))
        }

        assertFalse('A local-DB fixture must never request Object Server artifacts.', result.output.contains('object-server'))

        BuildResult cached = run(
            ':app:assembleDebug',
            ':app:assembleRelease',
            ':app:verifyRealmPluginContract',
            '--configuration-cache'
        ).build()
        assertTrue(
            'The second TestKit invocation must observe the configuration cache.',
            cached.output.contains('Reusing configuration cache.')
        )
    }

    @Test
    void syncIsRejectedBeforeAnyObjectServerDependencyCanResolve() {
        writeFixture(true)

        BuildResult result = run(':app:help', '--offline').buildAndFail()
        String lowerCaseOutput = result.output.toLowerCase(Locale.ROOT)

        assertTrue('syncEnabled=true must fail with an explicit Sync error.', lowerCaseOutput.contains('sync'))
        assertTrue('syncEnabled=true must fail as unsupported.', lowerCaseOutput.contains('unsupported'))
        assertFalse(
            'The deterministic Sync error must precede Object Server dependency selection.',
            lowerCaseOutput.contains('object-server')
        )
        assertFalse(
            'The deterministic Sync error must precede dependency-resolution failure.',
            lowerCaseOutput.contains('could not resolve')
        )
    }

    private GradleRunner run(String... arguments) {
        GradleRunner.create()
            .withProjectDir(consumerProject)
            .withArguments((arguments as List<String>) + ['--stacktrace', '--warning-mode', 'all'])
    }

    private void writeFixture(boolean syncEnabled) {
        consumerProject = temporaryFolder.newFolder('consumer')
        moduleProject = new File(consumerProject, 'app')
        fixtureRepository = temporaryFolder.newFolder('fork-repository')
        writeForkRepository()

        writeFile(new File(consumerProject, 'settings.gradle'), '''
            pluginManagement {
                repositories {
                    google()
                    mavenCentral()
                    gradlePluginPortal()
                }
            }
            rootProject.name = 'realm-plugin-test-fixture'
            include ':app'
        '''.stripIndent())
        writeFile(new File(consumerProject, 'build.gradle'), '')
        writeFile(new File(moduleProject, 'build.gradle'), consumerBuildScript(syncEnabled))
        writeSources()
    }

    private String consumerBuildScript(boolean syncEnabled) {
        boolean application = androidPlugin == 'application'
        boolean kotlin = language != 'java'
        String repositoryUri = fixtureRepository.toURI().toString()
        String androidPluginId = application ? 'com.android.application' : 'com.android.library'
        String applicationId = application ? "applicationId = 'io.realm.fixture'" : ''
        String realmBeforeAndroid = order == 'realm-then-android' ? "apply plugin: 'realm-android'" : ''
        String realmAfterAndroid = order == 'android-then-realm' ? "apply plugin: 'realm-android'" : ''
        String syncBlock = syncEnabled ? '''
            realm {
                syncEnabled = true
            }
        '''.stripIndent() : ''

        '''
            buildscript {
                repositories {
                    google()
                    mavenCentral()
                }
                dependencies {
                    classpath files(''' + pluginClasspath() + ''')
                    classpath 'com.android.tools.build:gradle:''' + AGP_VERSION + ''''
                }
            }

            repositories {
                maven { url = uri(''' + "'" + repositoryUri + "'" + ''') }
                google()
                mavenCentral()
            }

            ''' + realmBeforeAndroid + '''
            apply plugin: '''' + androidPluginId + ''''
            ''' + realmAfterAndroid + '''

            android {
                namespace = 'io.realm.fixture'
                compileSdk = 37

                defaultConfig {
                    ''' + applicationId + '''
                    minSdk = 21
                    targetSdk = 37
                    versionCode = 1
                    versionName = '1.0'
                }
            }

            ''' + syncBlock + '''

            tasks.register('verifyRealmPluginContract') {
                doLast {
                    def coordinate = { dependency ->
                        dependency.group + ':' + dependency.name + ':' + dependency.version
                    }
                    def realmDependencies = { configurationName ->
                        def configuration = configurations.findByName(configurationName)
                        if (configuration == null) {
                            return []
                        }
                        return configuration.dependencies
                            .findAll { it.group == 'io.github.leminity.realm' }
                            .collect(coordinate)
                            .sort()
                    }

                    ['api', 'annotationProcessor', 'androidTestAnnotationProcessor', 'kapt', 'kaptAndroidTest'].each { name ->
                        def dependencies = realmDependencies(name)
                        if (!dependencies.isEmpty()) {
                            println('REALM-DEPS ' + name + '=' + dependencies.join('|'))
                            println('REALM-COUNT ' + name + '=' + dependencies.size())
                        }
                    }

                    ['debugCompileClasspath', 'releaseCompileClasspath'].each { name ->
                        def configuration = configurations.getByName(name)
                        def components = configuration.incoming.resolutionResult.allComponents
                            .findAll { it.moduleVersion != null && it.moduleVersion.group == 'io.github.leminity.realm' }
                            .collect { it.moduleVersion.group + ':' + it.moduleVersion.name + ':' + it.moduleVersion.version }
                            .sort()
                        println('REALM-RESOLVED ' + name + '=' + components.join('|'))
                    }

                    println('REALM-LEGACY-KAPT=' + pluginManager.hasPlugin('com.android.legacy-kapt'))
                }
            }
        '''.stripIndent()
    }

    private void writeSources() {
        if (language == 'java' || language == 'mixed') {
            writeFile(
                new File(moduleProject, 'src/main/java/io/realm/fixture/JavaMarker.java'),
                'package io.realm.fixture; public final class JavaMarker { }'
            )
        }
        if (language == 'kotlin' || language == 'mixed') {
            writeFile(
                new File(moduleProject, 'src/main/kotlin/io/realm/fixture/KotlinMarker.kt'),
                'package io.realm.fixture\\nclass KotlinMarker'
            )
        }
        writeFile(
            new File(moduleProject, 'src/main/AndroidManifest.xml'),
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android" />'
        )
    }

    private void writeForkRepository() {
        writeJarModule('realm-annotations')
        writeJarModule('realm-annotations-processor')
        writeAarModule('realm-android-library')
        writeAarModule('realm-android-kotlin-extensions')
    }

    private void writeJarModule(String artifact) {
        File artifactDirectory = moduleDirectory(artifact)
        artifactDirectory.mkdirs()
        writePom(artifactDirectory, artifact, 'jar')
        new JarOutputStream(new FileOutputStream(new File(artifactDirectory, artifact + '-' + FORK_VERSION + '.jar'))).close()
    }

    private void writeAarModule(String artifact) {
        File artifactDirectory = moduleDirectory(artifact)
        artifactDirectory.mkdirs()
        writePom(artifactDirectory, artifact, 'aar')

        File aar = new File(artifactDirectory, artifact + '-' + FORK_VERSION + '.aar')
        ZipOutputStream output = new ZipOutputStream(new FileOutputStream(aar))
        try {
            writeZipEntry(
                output,
                'AndroidManifest.xml',
                '<manifest package="io.realm.fixture.stub" />'.getBytes('UTF-8')
            )
            writeZipEntry(output, 'classes.jar', emptyJar())
            writeZipEntry(output, 'R.txt', new byte[0])
        } finally {
            output.close()
        }
    }

    private File moduleDirectory(String artifact) {
        new File(fixtureRepository, FORK_GROUP.replace('.', '/') + '/' + artifact + '/' + FORK_VERSION)
    }

    private void writePom(File artifactDirectory, String artifact, String packaging) {
        writeFile(
            new File(artifactDirectory, artifact + '-' + FORK_VERSION + '.pom'),
            '''<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>''' + FORK_GROUP + '''</groupId>
  <artifactId>''' + artifact + '''</artifactId>
  <version>''' + FORK_VERSION + '''</version>
  <packaging>''' + packaging + '''</packaging>
</project>
'''
        )
    }

    private static byte[] emptyJar() {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream()
        JarOutputStream output = new JarOutputStream(bytes)
        output.close()
        bytes.toByteArray()
    }

    private static void writeZipEntry(ZipOutputStream output, String name, byte[] bytes) {
        output.putNextEntry(new ZipEntry(name))
        output.write(bytes)
        output.closeEntry()
    }

    private static void writeFile(File file, String contents) {
        file.parentFile.mkdirs()
        file.setText(contents, 'UTF-8')
    }

    private static String pluginClasspath() {
        String classpath = System.getProperty('realmPluginClasspath')
        assertNotNull('The Gradle test task must expose the plugin-under-test classpath.', classpath)
        classpath
            .split(Pattern.quote(File.pathSeparator))
            .collect { "'" + it.replace('\\', '\\\\').replace("'", "\\'") + "'" }
            .join(', ')
    }

    private void assertConfigurationContains(BuildResult result, String configuration, String artifact) {
        assertTrue(
            'Expected ' + configuration + ' to include the forked ' + artifact + ' coordinate.\\n' + result.output,
            result.output.contains('io.github.leminity.realm:' + artifact + ':' + FORK_VERSION)
        )
    }

    private void assertConfigurationCount(BuildResult result, String configuration, int expected) {
        assertTrue(
            'Expected exactly ' + expected + ' forked dependencies in ' + configuration + '.\\n' + result.output,
            result.output.contains('REALM-COUNT ' + configuration + '=' + expected)
        )
    }

    private static void assertTaskSucceeded(BuildResult result, String taskPath) {
        assertNotNull('Expected task ' + taskPath + ' to run.\\n' + result.output, result.task(taskPath))
        assertEquals(TaskOutcome.SUCCESS, result.task(taskPath).outcome)
    }
}
