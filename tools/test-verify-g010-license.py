#!/usr/bin/env python3
"""Regression tests for tools/verify-g010-license.py."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify-g010-license.py")
SPEC = importlib.util.spec_from_file_location("verify_g010_license", SCRIPT)
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


LICENSE = """Apache License
Version 2.0, January 2004
You must cause any modified files to carry prominent notices
""".encode()
NOTICE = """Realm Java Fork Notice
This distribution is based on Realm Java 10.19.0 and is maintained by Leminity.
Its modified files have changed from the upstream work.
This distribution includes locally modified Realm Core source backported from
c97091234d40efaaaf7d8d8349eb3c97012f6c9b.
Realm, Realm Java, and MongoDB names are used only to describe origin; no trademark rights are claimed.
This NOTICE is informational and does not modify the License.
""".encode()


def pom(artifact: str, version: str) -> str:
    return f"""<project><groupId>io.github.leminity.realm</groupId><artifactId>{artifact}</artifactId><version>{version}</version><description>Fixture. {VERIFY.POM_FORK_DISCLOSURE}</description><url>https://github.com/Leminity/realm-java</url><licenses><license><name>The Apache Software License, Version 2.0</name><url>https://www.apache.org/licenses/LICENSE-2.0.txt</url></license></licenses><issueManagement><system>github</system><url>https://github.com/Leminity/realm-java/issues</url></issueManagement><scm><url>https://github.com/Leminity/realm-java</url><connection>scm:git:https://github.com/Leminity/realm-java.git</connection><developerConnection>scm:git:ssh://git@github.com/Leminity/realm-java.git</developerConnection></scm><developers><developer><id>leminity</id><name>Leminity</name></developer></developers></project>"""


class VerifyG010LicenseTest(unittest.TestCase):
    def make_fixture(self) -> tuple[Path, Path]:
        temporary = Path(tempfile.mkdtemp())
        root = temporary / "root"
        repository = temporary / "repository"
        root.mkdir()
        (root / "LICENSE").write_bytes(LICENSE)
        (root / "NOTICE").write_bytes(NOTICE)
        (root / "version.txt").write_text("1.0.0", encoding="utf-8")
        core_license = root / "realm/realm-library/src/main/cpp/realm-core/LICENSE"
        core_license.parent.mkdir(parents=True)
        core_license.write_text("core", encoding="utf-8")
        catch_license = root / "realm/realm-library/src/main/cpp/realm-core/external/catch/LICENSE.txt"
        catch_license.parent.mkdir(parents=True)
        catch_license.write_text("catch", encoding="utf-8")
        core_root = root / "realm/realm-library/src/main/cpp/realm-core"
        for relative_path in VERIFY.CORE_BACKPORT_PATHS:
            core_path = core_root / relative_path
            core_path.parent.mkdir(parents=True, exist_ok=True)
            core_path.write_text(
                f"// {VERIFY.CORE_MODIFICATION_NOTICE}\n"
                f"// Backport source: {VERIFY.CORE_BACKPORT_SOURCE_COMMIT}.\n",
                encoding="utf-8",
            )
        for artifact, extension in VERIFY.ARTIFACTS.items():
            directory = repository / VERIFY.GROUP_PATH / artifact / "1.0.0"
            directory.mkdir(parents=True)
            for filename in (
                f"{artifact}-1.0.0.{extension}",
                f"{artifact}-1.0.0-sources.jar",
                f"{artifact}-1.0.0-javadoc.jar",
            ):
                with zipfile.ZipFile(directory / filename, "w") as archive:
                    archive.writestr("META-INF/LICENSE", LICENSE)
                    archive.writestr("META-INF/NOTICE", NOTICE)
            (directory / f"{artifact}-1.0.0.pom").write_text(pom(artifact, "1.0.0"), encoding="utf-8")
        return root, repository

    def test_accepts_complete_six_artifact_fixture(self) -> None:
        root, repository = self.make_fixture()
        report = VERIFY.validate_repository(repository, root)
        self.assertEqual(sorted(report["artifacts"]), sorted(VERIFY.ARTIFACTS))
        self.assertEqual(report["format"], "g010-apache-notice-v1")

    def test_requires_notice_in_every_archive(self) -> None:
        root, repository = self.make_fixture()
        archive = repository / VERIFY.GROUP_PATH / "realm-gradle-plugin" / "1.0.0" / "realm-gradle-plugin-1.0.0.jar"
        with zipfile.ZipFile(archive, "w") as replacement:
            replacement.writestr("META-INF/LICENSE", LICENSE)
        with self.assertRaisesRegex(VERIFY.ValidationError, "META-INF/NOTICE"):
            VERIFY.validate_repository(repository, root)

    def test_requires_root_notice(self) -> None:
        root, repository = self.make_fixture()
        (root / "NOTICE").unlink()
        with self.assertRaisesRegex(VERIFY.ValidationError, "root NOTICE"):
            VERIFY.validate_repository(repository, root)

    def test_rejects_generic_pom_description_without_fork_origin(self) -> None:
        root, repository = self.make_fixture()
        artifact = "realm-gradle-plugin"
        pom_path = repository / VERIFY.GROUP_PATH / artifact / "1.0.0" / f"{artifact}-1.0.0.pom"
        pom_path.write_text(pom(artifact, "1.0.0").replace(VERIFY.POM_FORK_DISCLOSURE, "fixture"), encoding="utf-8")
        with self.assertRaisesRegex(VERIFY.ValidationError, "unofficial Leminity fork"):
            VERIFY.validate_repository(repository, root)

    def test_requires_notice_in_every_modified_core_backport_file(self) -> None:
        root, repository = self.make_fixture()
        missing_notice = (
            root
            / "realm/realm-library/src/main/cpp/realm-core"
            / VERIFY.CORE_BACKPORT_PATHS[0]
        )
        missing_notice.write_text("// upstream contents only\n", encoding="utf-8")
        with self.assertRaisesRegex(VERIFY.ValidationError, "prominent Leminity Core backport notice"):
            VERIFY.validate_repository(repository, root)


if __name__ == "__main__":
    unittest.main()
