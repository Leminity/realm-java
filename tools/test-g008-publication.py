#!/usr/bin/env python3
"""Offline regression tests for the G008 local Maven repository validator."""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("g008-publication.py")
REPOSITORY_ROOT = MODULE_PATH.parents[1]
SPEC = importlib.util.spec_from_file_location("g008_publication", MODULE_PATH)
assert SPEC and SPEC.loader
G008 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G008)


def pom(artifact: str, dependencies: set[tuple[str, str]]) -> str:
    dependency_xml = "".join(
        "<dependency><groupId>io.github.leminity.realm</groupId>"
        f"<artifactId>{dependency}</artifactId><version>{version}</version>"
        "</dependency>"
        for dependency, version in sorted(dependencies)
    )
    return f"""<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>{G008.GROUP}</groupId>
  <artifactId>{artifact}</artifactId>
  <version>{G008.VERSION}</version>
  <name>{artifact}</name><description>G008 test artifact</description>
  <url>https://github.com/Leminity/realm-java</url>
  <licenses><license><name>Apache Software License, Version 2.0</name></license></licenses>
  <developers><developer><name>Leminity</name></developer></developers>
  <dependencies>{dependency_xml}</dependencies>
</project>"""


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
                content = pom(artifact, G008.FORK_EDGES[artifact]) if name.endswith(".pom") else name
                path.write_text(content, encoding="utf-8")
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
        extra = self.repository / "io/github/leminity/realm/internal-build-transformer/10.19.0-agp9.1"
        extra.mkdir(parents=True)
        (extra / "internal-build-transformer-10.19.0-agp9.1.jar").write_text("no", encoding="utf-8")
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
        self.assertNotIn('VERSION = "', validator_source)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
