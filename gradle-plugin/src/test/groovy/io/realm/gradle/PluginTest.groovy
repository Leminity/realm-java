// Modified by Leminity from the upstream Realm Java project.
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
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

import java.util.jar.JarOutputStream
import javax.tools.JavaCompiler
import javax.tools.ToolProvider
import java.util.regex.Pattern
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream

import static org.junit.Assert.assertEquals
import static org.junit.Assert.assertFalse
import static org.junit.Assert.assertNotNull
import static org.junit.Assert.assertTrue
import static org.junit.Assume.assumeTrue

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
    private static final String FORK_VERSION = releaseVersion()
    private static final String OFFICIAL_GROUP = 'io.realm'
    private static final String OFFICIAL_VERSION = '10.19.0'

    private static String releaseVersion() {
        File current = new File(System.getProperty('user.dir')).canonicalFile
        while (current != null) {
            File versionFile = new File(current, 'version.txt')
            if (versionFile.isFile()) {
                String version = versionFile.getText('UTF-8').trim()
                if (version) {
                    return version
                }
            }
            current = current.parentFile
        }
        throw new IllegalStateException('Unable to locate non-empty version.txt for plugin fixtures')
    }

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

    @Test
    void pluginPreservesTheForkedAndroidContractAcrossTheCompatibilityMatrix() {
        writeFixture(false)

        BuildResult result = run(
            ':app:assembleDebug',
            ':app:assembleRelease',
            ':app:verifyRealmPluginContract',
            ':app:dependencies',
            '--configuration',
            'api'
        ).build()

        assertTaskSucceeded(result, ':app:assembleDebug')
        assertTaskSucceeded(result, ':app:assembleRelease')
        assertTaskSucceeded(result, ':app:verifyRealmPluginContract')
        assertTaskSucceeded(result, ':app:debugRealmAccessorsTransformer')
        assertTaskSucceeded(result, ':app:releaseRealmAccessorsTransformer')

        assertConfigurationContains(result, 'api', 'realm-annotations')
        assertConfigurationContains(result, 'api', 'realm-android-library')
        assertConfigurationCount(result, 'api', language == 'java' ? 2 : 3)
        assertResolvedConfigurationContains(result, 'debugCompileClasspath', 'realm-annotations')
        assertResolvedConfigurationContains(result, 'debugCompileClasspath', 'realm-android-library')
        assertResolvedConfigurationContains(result, 'releaseCompileClasspath', 'realm-annotations')
        assertResolvedConfigurationContains(result, 'releaseCompileClasspath', 'realm-android-library')
        assertTrue('The plugin must remove owned official Realm dependencies.', result.output.contains('REALM-OFFICIAL-COUNT api=0'))
        assertTrue('debug resolution must not retain official Realm modules.', result.output.contains('REALM-OFFICIAL-RESOLVED debugCompileClasspath=0'))
        assertTrue('release resolution must not retain official Realm modules.', result.output.contains('REALM-OFFICIAL-RESOLVED releaseCompileClasspath=0'))
        assertGeneratedAccessor(result, 'JavaRealmModel', language == 'java' || language == 'mixed')
        assertGeneratedAccessor(result, 'KotlinRealmModel', language == 'kotlin' || language == 'mixed')

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

        BuildResult offline = run(':app:verifyRealmPluginContract', '--offline').build()
        assertTrue('The warmed fixture must resolve its local Realm contract offline.', offline.output.contains('REALM-OFFICIAL-COUNT api=0'))

        List<String> cacheArguments = [
            ':app:assembleDebug',
            ':app:assembleRelease',
            '--configuration-cache',
            '--offline'
        ]
        run(*(cacheArguments as String[])).build()
        BuildResult cached = run(*(cacheArguments as String[])).build()
        assertTrue(
            'The second TestKit invocation must observe the configuration cache.',
            cached.output.contains('Reusing configuration cache.')
        )
    }

    @Test
    void explicitSyncFalseKeepsTheLocalRealmContract() {
        writeFixture(false, true)

        BuildResult result = run(':app:verifyRealmPluginContract').build()
        assertTrue(result.output.contains('REALM-OFFICIAL-COUNT api=0'))
        assertFalse(result.output.contains('object-server'))

        BuildResult offline = run(':app:verifyRealmPluginContract', '--offline').build()
        assertTrue('Explicit syncEnabled=false must remain runnable offline after warm-up.', offline.output.contains('REALM-OFFICIAL-COUNT api=0'))
    }

    @Test
    void kotlinExtensionDslPreservesExplicitFalseAndDefaultsTrue() {
        assumeTrue(androidPlugin == 'application' && language == 'kotlin' && order == 'android-then-realm')

        writeFixture(false, false, false)
        BuildResult explicitlyDisabled = run(':app:dependencies', '--configuration', 'api').build()
        assertFalse(explicitlyDisabled.output.contains(forkCoordinate('realm-android-kotlin-extensions')))

        writeFixture(false)
        BuildResult defaultEnabled = run(':app:dependencies', '--configuration', 'api').build()
        assertTrue(defaultEnabled.output.contains(forkCoordinate('realm-android-kotlin-extensions')))
    }

    @Test
    void syncIsRejectedBeforeAnyObjectServerDependencyCanResolve() {
        writeFixture(true)

        BuildResult result = run(':app:help').buildAndFail()
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

    private void writeFixture(
        boolean syncEnabled,
        boolean explicitSyncDisabled = false,
        Boolean kotlinExtensionsEnabled = null
    ) {
        consumerProject = temporaryFolder.newFolder('consumer-' + System.nanoTime())
        moduleProject = new File(consumerProject, 'app')
        fixtureRepository = temporaryFolder.newFolder('fork-repository-' + System.nanoTime())
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
        writeFile(
            new File(moduleProject, 'build.gradle'),
            consumerBuildScript(syncEnabled, explicitSyncDisabled, kotlinExtensionsEnabled)
        )
        writeSources()
    }

    private String consumerBuildScript(
        boolean syncEnabled,
        boolean explicitSyncDisabled,
        Boolean kotlinExtensionsEnabled
    ) {
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
        '''.stripIndent() : explicitSyncDisabled ? '''
            realm {
                syncEnabled = false
            }
        '''.stripIndent() : ''
        String kotlinExtensionsBlock = kotlinExtensionsEnabled == null ? '' : '''
            realm {
                kotlinExtensionsEnabled = ''' + kotlinExtensionsEnabled + '''
            }
        '''.stripIndent()
        String javaOnlyKotlinSetting = language == 'java' ? 'enableKotlin = false' : ''

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
                ''' + javaOnlyKotlinSetting + '''

                defaultConfig {
                    ''' + applicationId + '''
                    minSdk = 21
                    targetSdk = 37
                    versionCode = 1
                    versionName = '1.0'
                }
            }

            dependencies {
                api 'io.realm:realm-android-library:''' + OFFICIAL_VERSION + ''''
                ''' + (kotlin ? "api 'io.realm:realm-android-kotlin-extensions:" + OFFICIAL_VERSION + "'" : '') + '''
            }

            ''' + syncBlock + '''
            ''' + kotlinExtensionsBlock + '''

            tasks.register('verifyRealmPluginContract') {
                dependsOn 'assembleDebug', 'assembleRelease'
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
                    def official = configurations.getByName('api').dependencies
                        .findAll { it.group == 'io.realm' }
                    println('REALM-OFFICIAL-COUNT api=' + official.size())

                    ['debugCompileClasspath', 'releaseCompileClasspath'].each { name ->
                        def configuration = configurations.getByName(name)
                        def components = configuration.incoming.resolutionResult.allComponents
                            .findAll { it.moduleVersion != null && it.moduleVersion.group == 'io.github.leminity.realm' }
                            .collect { it.moduleVersion.group + ':' + it.moduleVersion.name + ':' + it.moduleVersion.version }
                            .sort()
                        println('REALM-RESOLVED ' + name + '=' + components.join('|'))
                        def officialComponents = configuration.incoming.resolutionResult.allComponents
                            .findAll { it.moduleVersion != null && it.moduleVersion.group == 'io.realm' }
                        println('REALM-OFFICIAL-RESOLVED ' + name + '=' + officialComponents.size())
                    }

                    println('REALM-LEGACY-KAPT=' + pluginManager.hasPlugin('com.android.legacy-kapt'))

                    def generated = fileTree(buildDir).matching {
                        include '**/Generated*RealmAccessor.java'
                    }.files.collect { it.name }.sort()
                    println('REALM-GENERATED=' + generated.join('|'))
                }
            }
        '''.stripIndent()
    }

    private void writeSources() {
        if (language == 'java' || language == 'mixed') {
            writeFile(
                new File(moduleProject, 'src/main/java/io/realm/fixture/JavaRealmModel.java'),
                '''package io.realm.fixture;
                   import io.realm.RealmObject;
                   import io.realm.annotations.RealmClass;
                   @RealmClass public final class JavaRealmModel extends RealmObject { }'''
            )
        }
        if (language == 'kotlin' || language == 'mixed') {
            writeFile(
                new File(moduleProject, 'src/main/kotlin/io/realm/fixture/KotlinRealmModel.kt'),
                '''package io.realm.fixture
                   import io.realm.RealmObject
                   import io.realm.annotations.RealmClass
                   @RealmClass class KotlinRealmModel : RealmObject()'''
            )
        }
        writeFile(
            new File(moduleProject, 'src/main/AndroidManifest.xml'),
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android" />'
        )
    }

    private void writeForkRepository() {
        writeAnnotationsModule(FORK_GROUP, FORK_VERSION)
        writeProcessorModule(FORK_GROUP, FORK_VERSION)
        writeRealmLibraryModule(FORK_GROUP, FORK_VERSION)
        writeEmptyAarModule(FORK_GROUP, FORK_VERSION, 'realm-android-kotlin-extensions')

        // The consumer starts with these obsolete coordinates. Realm.kt must remove them.
        writeRealmLibraryModule(OFFICIAL_GROUP, OFFICIAL_VERSION)
        writeEmptyAarModule(OFFICIAL_GROUP, OFFICIAL_VERSION, 'realm-android-kotlin-extensions')
    }

    private void writeAnnotationsModule(String group, String version) {
        File artifactDirectory = moduleDirectory(group, 'realm-annotations', version)
        artifactDirectory.mkdirs()
        writePom(artifactDirectory, group, 'realm-annotations', version, 'jar')
        writeBytes(
            new File(artifactDirectory, 'realm-annotations-' + version + '.jar'),
            compiledJar([
                'io/realm/annotations/RealmClass.java': '''package io.realm.annotations;
                    import java.lang.annotation.ElementType;
                    import java.lang.annotation.Retention;
                    import java.lang.annotation.RetentionPolicy;
                    import java.lang.annotation.Target;
                    @Retention(RetentionPolicy.SOURCE) @Target(ElementType.TYPE)
                    public @interface RealmClass { }'''
            ])
        )
    }

    private void writeProcessorModule(String group, String version) {
        File artifactDirectory = moduleDirectory(group, 'realm-annotations-processor', version)
        artifactDirectory.mkdirs()
        writePom(artifactDirectory, group, 'realm-annotations-processor', version, 'jar')
        byte[] processorJar = compiledJar(
                [
                    'io/realm/annotations/RealmClass.java': '''package io.realm.annotations;
                        import java.lang.annotation.ElementType;
                        import java.lang.annotation.Retention;
                        import java.lang.annotation.RetentionPolicy;
                        import java.lang.annotation.Target;
                        @Retention(RetentionPolicy.SOURCE) @Target(ElementType.TYPE)
                        public @interface RealmClass { }''',
                    'io/realm/fixture/processor/FixtureRealmProcessor.java': '''package io.realm.fixture.processor;
                        import io.realm.annotations.RealmClass;
                        import java.io.IOException;
                        import java.io.Writer;
                        import java.util.Set;
                        import javax.annotation.processing.AbstractProcessor;
                        import javax.annotation.processing.Filer;
                        import javax.annotation.processing.ProcessingEnvironment;
                        import javax.annotation.processing.RoundEnvironment;
                        import javax.annotation.processing.SupportedAnnotationTypes;
                        import javax.annotation.processing.SupportedSourceVersion;
                        import javax.lang.model.SourceVersion;
                        import javax.lang.model.element.Element;
                        import javax.lang.model.element.TypeElement;
                        import javax.tools.JavaFileObject;
                        @SupportedAnnotationTypes("io.realm.annotations.RealmClass")
                        @SupportedSourceVersion(SourceVersion.RELEASE_8)
                        public final class FixtureRealmProcessor extends AbstractProcessor {
                            @Override public boolean process(
                                    Set<? extends TypeElement> annotations, RoundEnvironment roundEnvironment) {
                                if (roundEnvironment.processingOver()) return false;
                                for (Element element : roundEnvironment.getElementsAnnotatedWith(RealmClass.class)) {
                                    String model = element.getSimpleName().toString();
                                    try {
                                        JavaFileObject file = processingEnv.getFiler().createSourceFile(
                                                "io.realm.fixture.Generated" + model + "RealmAccessor");
                                        try (Writer writer = file.openWriter()) {
                                            writer.write("package io.realm.fixture; public final class Generated"
                                                    + model + "RealmAccessor { public static final String MODEL = \\""
                                                    + model + "\\"; }");
                                        }
                                    } catch (IOException exception) {
                                        throw new IllegalStateException(exception);
                                    }
                                }
                                return false;
                            }
                        }'''
                ],
                ['META-INF/services/javax.annotation.processing.Processor':
                    "io.realm.fixture.processor.FixtureRealmProcessor\n".getBytes('UTF-8')]
            )
        assertProcessorServiceEntry(processorJar)
        writeBytes(new File(artifactDirectory, 'realm-annotations-processor-' + version + '.jar'), processorJar)
    }

    private void writeRealmLibraryModule(String group, String version) {
        File artifactDirectory = moduleDirectory(group, 'realm-android-library', version)
        artifactDirectory.mkdirs()
        writePom(artifactDirectory, group, 'realm-android-library', version, 'aar')
        writeAar(
            new File(artifactDirectory, 'realm-android-library-' + version + '.aar'),
            compiledJar([
                'io/realm/RealmObject.java': 'package io.realm; public class RealmObject { }',
                'io/realm/internal/RealmObjectProxy.java': '''package io.realm.internal;
                    public interface RealmObjectProxy { void realm$injectObjectContext(); }''',
                'io/realm/internal/RealmProxyMediator.java': '''package io.realm.internal;
                    public abstract class RealmProxyMediator { }'''
            ])
        )
    }

    private void writeEmptyAarModule(String group, String version, String artifact) {
        File artifactDirectory = moduleDirectory(group, artifact, version)
        artifactDirectory.mkdirs()
        writePom(artifactDirectory, group, artifact, version, 'aar')
        writeAar(new File(artifactDirectory, artifact + '-' + version + '.aar'), emptyJar())
    }

    private static void writeAar(File aar, byte[] classesJar) {
        ZipOutputStream output = new ZipOutputStream(new FileOutputStream(aar))
        try {
            String fixtureNamespace = 'io.realm.fixture.' + aar.name
                .replaceAll(/[^A-Za-z0-9_]/, '_')
                .replaceFirst(/^([0-9])/, '_$1')
            writeZipEntry(
                output,
                'AndroidManifest.xml',
                ('<manifest package="' + fixtureNamespace + '" />').getBytes('UTF-8')
            )
            writeZipEntry(output, 'classes.jar', classesJar)
            writeZipEntry(output, 'R.txt', new byte[0])
        } finally {
            output.close()
        }
    }

    private File moduleDirectory(String group, String artifact, String version) {
        new File(fixtureRepository, group.replace('.', '/') + '/' + artifact + '/' + version)
    }

    private void writePom(File artifactDirectory, String group, String artifact, String version, String packaging) {
        writeFile(
            new File(artifactDirectory, artifact + '-' + version + '.pom'),
            '''<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>''' + group + '''</groupId>
  <artifactId>''' + artifact + '''</artifactId>
  <version>''' + version + '''</version>
  <packaging>''' + packaging + '''</packaging>
</project>
'''
        )
    }

    private byte[] compiledJar(Map<String, String> sources, Map<String, byte[]> resources = [:]) {
        File compilerRoot = temporaryFolder.newFolder('compiled-' + System.nanoTime())
        File sourceRoot = new File(compilerRoot, 'src')
        File classRoot = new File(compilerRoot, 'classes')
        List<File> sourceFiles = []
        sources.each { relativePath, contents ->
            File source = new File(sourceRoot, relativePath)
            writeFile(source, contents.stripIndent())
            sourceFiles.add(source)
        }

        JavaCompiler compiler = ToolProvider.systemJavaCompiler
        assertNotNull('A JDK compiler is required to create the isolated fixture artifacts.', compiler)
        List<String> arguments = ['-source', '8', '-target', '8', '-d', classRoot.absolutePath]
        arguments.addAll(sourceFiles.collect { it.absolutePath })
        assertEquals('The fixture artifact sources must compile.', 0, compiler.run(null, null, null, *(arguments as String[])))

        ByteArrayOutputStream bytes = new ByteArrayOutputStream()
        JarOutputStream output = new JarOutputStream(bytes)
        try {
            classRoot.eachFileRecurse { file ->
                if (file.isFile()) {
                    String name = classRoot.toPath().relativize(file.toPath()).toString().replace(File.separatorChar, '/' as char)
                    writeZipEntry(output, name, file.bytes)
                }
            }
            resources.each { name, contents -> writeZipEntry(output, name, contents) }
        } finally {
            output.close()
        }
        bytes.toByteArray()
    }

    private static void assertProcessorServiceEntry(byte[] jar) {
        String path = 'META-INF/services/javax.annotation.processing.Processor'
        ZipInputStream input = new ZipInputStream(new ByteArrayInputStream(jar))
        try {
            ZipEntry entry
            while ((entry = input.nextEntry) != null) {
                if (entry.name == path) {
                    ByteArrayOutputStream bytes = new ByteArrayOutputStream()
                    byte[] buffer = new byte[256]
                    int read
                    while ((read = input.read(buffer)) != -1) {
                        bytes.write(buffer, 0, read)
                    }
                    assertEquals(
                        'The processor service entry must end with an actual newline byte.',
                        'io.realm.fixture.processor.FixtureRealmProcessor\n',
                        new String(bytes.toByteArray(), 'UTF-8')
                    )
                    return
                }
            }
            assertTrue('The processor JAR must contain its ServiceLoader entry.', false)
        } finally {
            input.close()
        }
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

    private static void writeBytes(File file, byte[] contents) {
        file.parentFile.mkdirs()
        file.bytes = contents
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
            result.output.readLines().any { line ->
                line.startsWith('REALM-DEPS ' + configuration + '=')
                    && line.contains(FORK_GROUP + ':' + artifact + ':' + FORK_VERSION)
            }
        )
    }

    private void assertResolvedConfigurationContains(BuildResult result, String configuration, String artifact) {
        String marker = 'REALM-RESOLVED ' + configuration + '='
        String coordinate = FORK_GROUP + ':' + artifact + ':' + FORK_VERSION
        assertTrue(
            'Expected ' + configuration + ' to resolve the forked ' + artifact + ' coordinate.\n' + result.output,
            result.output.readLines().any { line -> line.contains(marker) && line.contains(coordinate) }
        )
    }

    private void assertConfigurationCount(BuildResult result, String configuration, int expected) {
        assertTrue(
            'Expected exactly ' + expected + ' forked dependencies in ' + configuration + '.\\n' + result.output,
            result.output.contains('REALM-COUNT ' + configuration + '=' + expected)
        )
    }

    private static String forkCoordinate(String artifact) {
        FORK_GROUP + ':' + artifact + ':' + FORK_VERSION
    }

    private static void assertGeneratedAccessor(BuildResult result, String model, boolean expected) {
        String accessor = 'Generated' + model + 'RealmAccessor.java'
        if (expected) {
            assertTrue(
                'Expected a concrete accessor generated for ' + model + '.\\n' + result.output,
                result.output.contains(accessor)
            )
        } else {
            assertFalse(
                'Did not expect an accessor for an absent ' + model + '.\\n' + result.output,
                result.output.contains(accessor)
            )
        }
    }

    private static void assertTaskSucceeded(BuildResult result, String taskPath) {
        assertNotNull('Expected task ' + taskPath + ' to run.\\n' + result.output, result.task(taskPath))
        assertEquals(TaskOutcome.SUCCESS, result.task(taskPath).outcome)
    }
}
