#!/usr/bin/env python3
"""Offline regression tests for the G008 local Maven repository validator."""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree


MODULE_PATH = Path(__file__).with_name("g008-publication.py")
REPOSITORY_ROOT = MODULE_PATH.parents[1]
SPEC = importlib.util.spec_from_file_location("g008_publication", MODULE_PATH)
assert SPEC and SPEC.loader
G008 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G008)


def tag_name(node: ElementTree.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def direct_child(node: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((child for child in node if tag_name(child) == name), None)


def staged_pom_from_official(artifact: str) -> ElementTree.Element:
    """Build a metadata-valid fork POM from the pinned full-edge oracle."""
    oracle = G008.OFFICIAL_POM_DIRECTORY / f"{artifact}-{G008.OFFICIAL_POM_VERSION}.pom"
    root = ElementTree.parse(oracle).getroot()
    for node in root.iter():
        if tag_name(node) == "groupId" and (node.text or "").strip() == "io.realm":
            node.text = G008.GROUP
        elif tag_name(node) == "version" and (node.text or "").strip() == G008.OFFICIAL_POM_VERSION:
            node.text = G008.VERSION
        elif tag_name(node) == "url" and (node.text or "").strip() == "https://docs.mongodb.com/realm":
            node.text = "https://github.com/Leminity/realm-java"
        elif tag_name(node) == "name" and (node.text or "").strip() == "Realm":
            node.text = "Leminity"
    dependencies = direct_child(root, "dependencies")
    if artifact == "realm-gradle-plugin" and dependencies is not None:
        for dependency in list(dependencies):
            group = direct_child(dependency, "groupId")
            name = direct_child(dependency, "artifactId")
            if (group.text, name.text) == ("com.neenbedankt.gradle.plugins", "android-apt"):
                dependencies.remove(dependency)
    return root


def populate_repository(repository: Path) -> None:
    for artifact, extension in G008.ARTIFACTS.items():
        directory = G008.coordinate_directory(repository, artifact)
        directory.mkdir(parents=True)
        for name in G008.expected_deployables(artifact, extension):
            path = directory / name
            if name.endswith(".aar"):
                with zipfile.ZipFile(path, "w") as archive:
                    for abi in sorted(G008.ANDROID_ABIS):
                        archive.writestr(f"jni/{abi}/librealm-jni.so", abi)
            else:
                if name.endswith(".pom"):
                    ElementTree.ElementTree(staged_pom_from_official(artifact)).write(
                        path, encoding="utf-8", xml_declaration=True
                    )
                else:
                    path.write_text(name, encoding="utf-8")
    G008.write_checksums(repository)


class G008PublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = Path(self.tempdir.name) / "repository"
        populate_repository(self.repository)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_exact_six_repository_validates_and_bundle_is_repeatable(self) -> None:
        report = G008.validate_repository(self.repository, False, None)
        self.assertEqual(report["coordinates"], [
            f"{G008.GROUP}:{artifact}:{G008.VERSION}" for artifact in G008.ARTIFACTS
        ])
        bundle = Path(self.tempdir.name) / "bundle.zip"
        first = G008.write_deterministic_bundle(bundle, self.repository)
        second = G008.write_deterministic_bundle(bundle, self.repository)
        self.assertEqual(first, second)
        self.assertEqual(first, hashlib.sha256(bundle.read_bytes()).hexdigest())

    def test_extra_coordinate_is_rejected(self) -> None:
        extra = self.repository / "io/github/leminity/realm/internal-build-transformer" / G008.VERSION
        extra.mkdir(parents=True)
        (extra / f"internal-build-transformer-{G008.VERSION}.jar").write_text(
            "no", encoding="utf-8"
        )
        with self.assertRaisesRegex(G008.ValidationError, "outside exact-six"):
            G008.validate_repository(self.repository, False, None)

    def test_extra_classifier_and_checksum_recursion_are_rejected(self) -> None:
        directory = G008.coordinate_directory(self.repository, "realm-transformer")
        (directory / f"realm-transformer-{G008.VERSION}-x86.jar").write_text("no", encoding="utf-8")
        with self.assertRaisesRegex(G008.ValidationError, "unexpected classifiers"):
            G008.validate_repository(self.repository, False, None)
        (directory / f"realm-transformer-{G008.VERSION}-x86.jar").unlink()
        (directory / f"realm-transformer-{G008.VERSION}.jar.asc.sha256").write_text("bad", encoding="utf-8")
        with self.assertRaisesRegex(G008.ValidationError, "unexpected classifiers"):
            G008.validate_repository(self.repository, False, None)

    def test_checksum_writer_removes_gradle_signature_checksum_recursion(self) -> None:
        directory = G008.coordinate_directory(self.repository, "realm-transformer")
        recursive = [
            directory / f"realm-transformer-{G008.VERSION}.jar.asc.md5",
            directory / f"realm-transformer-{G008.VERSION}.jar.asc.sha1",
            directory / f"realm-transformer-{G008.VERSION}.jar.md5.sha256",
        ]
        for path in recursive:
            path.write_text("bad", encoding="utf-8")
        G008.write_checksums(self.repository)
        for path in recursive:
            self.assertFalse(path.exists())
        G008.validate_repository(self.repository, False, None)

    def test_module_metadata_and_secret_payload_are_rejected(self) -> None:
        directory = G008.coordinate_directory(self.repository, "realm-gradle-plugin")
        (directory / f"realm-gradle-plugin-{G008.VERSION}.module").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(G008.ValidationError, "unexpected classifiers"):
            G008.validate_repository(self.repository, False, None)
        (directory / f"realm-gradle-plugin-{G008.VERSION}.module").unlink()
        primary = directory / f"realm-gradle-plugin-{G008.VERSION}.jar"
        primary.write_bytes(b"-----BEGIN PGP PRIVATE KEY BLOCK-----")
        G008.write_checksums(self.repository)
        with self.assertRaisesRegex(G008.ValidationError, "credential/private-key"):
            G008.validate_repository(self.repository, False, None)

    def test_required_signatures_are_cryptographically_enforced(self) -> None:
        with self.assertRaisesRegex(G008.ValidationError, "missing PGP signature"):
            G008.validate_repository(self.repository, True, None)

    def test_base_library_aar_rejects_x86_or_missing_abi(self) -> None:
        aar = G008.coordinate_directory(self.repository, "realm-android-library") / (
            f"realm-android-library-{G008.VERSION}.aar"
        )
        with zipfile.ZipFile(aar, "a") as archive:
            archive.writestr("jni/x86/librealm-jni.so", "x86")
        G008.write_checksums(self.repository)
        with self.assertRaisesRegex(G008.ValidationError, "JNI ABI directories"):
            G008.validate_repository(self.repository, False, None)

    def test_version_file_is_the_only_release_version_source(self) -> None:
        version_file = REPOSITORY_ROOT / "version.txt"
        self.assertEqual(G008.VERSION, version_file.read_text(encoding="utf-8").strip())

        publication_properties = (REPOSITORY_ROOT / "mavencentral-properties.gradle").read_text(
            encoding="utf-8"
        )
        self.assertIn('new File(buildscript.sourceFile.getParentFile(), "version.txt")', publication_properties)
        self.assertNotIn(G008.VERSION, publication_properties)

        plugin_source = (
            REPOSITORY_ROOT / "gradle-plugin/src/main/kotlin/io/realm/gradle/Realm.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("Version.VERSION", plugin_source)
        self.assertNotIn("FORK_VERSION", plugin_source)
        self.assertNotIn(G008.VERSION, plugin_source)

        validator_source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn('REPOSITORY_ROOT / "version.txt"', validator_source)
        self.assertNotRegex(validator_source, r'(?m)^VERSION = ["\']')

        consumer_source = (REPOSITORY_ROOT / "tools/g008-clean-consumer.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('"$root/version.txt"', consumer_source)
        self.assertNotIn(G008.VERSION, consumer_source)

        plugin_test_source = (
            REPOSITORY_ROOT / "gradle-plugin/src/test/groovy/io/realm/gradle/PluginTest.groovy"
        ).read_text(encoding="utf-8")
        self.assertIn("releaseVersion()", plugin_test_source)
        self.assertNotIn(G008.VERSION, plugin_test_source)

    def test_g008_gradle_tasks_use_the_gradle9_execution_api(self) -> None:
        build_script = (REPOSITORY_ROOT / "build.gradle").read_text(encoding="utf-8")
        self.assertIn("project.providers.exec", build_script)
        self.assertIn("runG008Command([", build_script)
        self.assertNotIn("doLast {\n        exec {", build_script)
        for property_name in ("g008StagingRepository", "g008ManifestFile", "g008BundleFile"):
            self.assertIn(
                f"project.findProperty('{property_name}') ?: System.getenv('{property_name}')",
                build_script,
            )

    def test_external_pom_edges_match_the_pinned_official_oracle(self) -> None:
        for artifact in G008.ARTIFACTS:
            staged = Path(self.tempdir.name) / f"{artifact}.pom"
            ElementTree.ElementTree(staged_pom_from_official(artifact)).write(
                staged, encoding="utf-8", xml_declaration=True
            )
            G008.validate_external_pom_edge_parity(staged, artifact)

        source = Path(self.tempdir.name) / "realm-gradle-plugin.pom"
        ElementTree.ElementTree(staged_pom_from_official("realm-gradle-plugin")).write(
            source, encoding="utf-8", xml_declaration=True
        )
        modified = Path(self.tempdir.name) / "realm-gradle-plugin.pom"
        root = ElementTree.parse(source).getroot()
        dependencies = direct_child(root, "dependencies")
        assert dependencies is not None
        injected = ElementTree.SubElement(dependencies, "dependency")
        ElementTree.SubElement(injected, "groupId").text = "com.android.tools.build"
        ElementTree.SubElement(injected, "artifactId").text = "gradle-kotlin"
        ElementTree.SubElement(injected, "version").text = "9.1.1"
        ElementTree.SubElement(injected, "scope").text = "runtime"
        ElementTree.ElementTree(root).write(modified, encoding="utf-8", xml_declaration=True)
        with self.assertRaisesRegex(G008.ValidationError, "external POM edges differ"):
            G008.validate_external_pom_edge_parity(modified, "realm-gradle-plugin")

        base = Path(self.tempdir.name) / "realm-android-library.pom"
        root = staged_pom_from_official("realm-android-library")
        dependencies = direct_child(root, "dependencies")
        assert dependencies is not None
        duplicate_bson = [
            dependency
            for dependency in dependencies
            if (direct_child(dependency, "groupId").text, direct_child(dependency, "artifactId").text)
            == ("org.mongodb", "bson")
        ]
        self.assertEqual(2, len(duplicate_bson))
        dependencies.remove(duplicate_bson[-1])
        ElementTree.ElementTree(root).write(base, encoding="utf-8", xml_declaration=True)
        with self.assertRaisesRegex(G008.ValidationError, "external POM edges differ"):
            G008.validate_external_pom_edge_parity(base, "realm-android-library")


if __name__ == "__main__":
    unittest.main(verbosity=2)
