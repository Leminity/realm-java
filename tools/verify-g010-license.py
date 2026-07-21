#!/usr/bin/env python3
"""Verify Apache-2.0 notice and publication metadata for the G010 artifacts.

The verifier is intentionally local-only.  It checks the source notices and
the six staged Maven coordinates without resolving dependencies or contacting
any publishing service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


GROUP_PATH = Path("io/github/leminity/realm")
ARTIFACTS = {
    "realm-gradle-plugin": "jar",
    "realm-transformer": "jar",
    "realm-annotations": "jar",
    "realm-annotations-processor": "jar",
    "realm-android-library": "aar",
    "realm-android-kotlin-extensions": "aar",
}
FORK_URL = "https://github.com/Leminity/realm-java"
UPSTREAM_URL = "https://github.com/realm/realm-java"
APACHE_NAME = "The Apache Software License, Version 2.0"
POM_FORK_DISCLOSURE = (
    "Unofficial Leminity maintenance fork of upstream Realm Java 10.19.0 "
    f"({UPSTREAM_URL})."
)
CORE_BACKPORT_SOURCE_COMMIT = "c97091234d40efaaaf7d8d8349eb3c97012f6c9b"
CORE_MODIFICATION_NOTICE = "Modified by the Leminity maintenance fork from upstream Realm Core."
CORE_BACKPORT_PATHS = (
    "src/realm/alloc.hpp",
    "src/realm/alloc_slab.cpp",
    "src/realm/util/encrypted_file_mapping.cpp",
    "src/realm/util/encrypted_file_mapping.hpp",
    "src/realm/util/file.cpp",
    "src/realm/util/file.hpp",
    "src/realm/util/file_mapper.cpp",
    "src/realm/util/file_mapper.hpp",
    "test/test_alloc.cpp",
    "test/test_encrypted_file_mapping.cpp",
    "test/test_shared.cpp",
)


class ValidationError(RuntimeError):
    """Raised when a source or staged publication legal invariant fails."""


def sha256_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def child(node: ElementTree.Element, name: str) -> ElementTree.Element | None:
    for candidate in node:
        if candidate.tag.rsplit("}", 1)[-1] == name:
            return candidate
    return None


def child_text(node: ElementTree.Element | None, name: str) -> str:
    if node is None:
        return ""
    candidate = child(node, name)
    return (candidate.text or "").strip() if candidate is not None else ""


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise ValidationError(f"missing {label}: {path}")
    return path


def validate_source_notices(root: Path) -> tuple[bytes, bytes]:
    license_contents = require_file(root / "LICENSE", "root Apache-2.0 LICENSE").read_bytes()
    notice_contents = require_file(root / "NOTICE", "root NOTICE").read_bytes()
    license_text = license_contents.decode("utf-8")
    notice_text = notice_contents.decode("utf-8")
    for required in (
        "Apache License",
        "Version 2.0, January 2004",
        "You must cause any modified files to carry prominent notices",
    ):
        if required not in license_text:
            raise ValidationError(f"root LICENSE is not the preserved Apache-2.0 text: missing {required!r}")
    for required in (
        "Realm Java Fork Notice",
        "Realm Java 10.19.0",
        "Leminity",
        "changed from the upstream work",
        "no trademark rights",
        "does not modify the License",
        "locally modified Realm Core source",
        CORE_BACKPORT_SOURCE_COMMIT,
    ):
        if required not in notice_text:
            raise ValidationError(f"root NOTICE is missing required fork attribution: {required!r}")
    core_root = root / "realm/realm-library/src/main/cpp/realm-core"
    require_file(core_root / "LICENSE", "Realm Core license")
    require_file(
        root / "realm/realm-library/src/main/cpp/realm-core/external/catch/LICENSE.txt",
        "bundled Catch license",
    )
    for relative_path in CORE_BACKPORT_PATHS:
        core_path = require_file(core_root / relative_path, f"modified Realm Core file {relative_path}")
        core_text = core_path.read_text(encoding="utf-8")
        for required in (CORE_MODIFICATION_NOTICE, CORE_BACKPORT_SOURCE_COMMIT):
            if required not in core_text:
                raise ValidationError(
                    f"{core_path}: missing prominent Leminity Core backport notice: {required!r}"
                )
    return license_contents, notice_contents


def validate_archive(path: Path, license_contents: bytes, notice_contents: bytes) -> dict[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            for entry, expected in (
                ("META-INF/LICENSE", license_contents),
                ("META-INF/NOTICE", notice_contents),
            ):
                if entry not in names:
                    raise ValidationError(f"{path}: missing {entry}")
                if archive.read(entry) != expected:
                    raise ValidationError(f"{path}: {entry} differs from the root source notice")
    except zipfile.BadZipFile as error:
        raise ValidationError(f"{path}: invalid ZIP publication artifact: {error}") from error
    return {"sha256": sha256_bytes(path.read_bytes())}


def validate_pom(path: Path, artifact: str, version: str) -> None:
    try:
        project = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as error:
        raise ValidationError(f"{path}: invalid POM XML: {error}") from error
    required = {
        "groupId": "io.github.leminity.realm",
        "artifactId": artifact,
        "version": version,
        "description": None,
        "url": FORK_URL,
    }
    for name, expected in required.items():
        actual = child_text(project, name)
        if (expected is None and not actual) or (expected is not None and actual != expected):
            raise ValidationError(f"{path}: expected {name}={expected!r}, found {actual!r}")
    description = child_text(project, "description")
    if POM_FORK_DISCLOSURE not in description:
        raise ValidationError(
            f"{path}: description must identify the unofficial Leminity fork and upstream origin"
        )
    licenses = child(project, "licenses")
    license_node = child(licenses, "license") if licenses is not None else None
    if child_text(license_node, "name") != APACHE_NAME:
        raise ValidationError(f"{path}: missing Apache-2.0 POM license name")
    if child_text(license_node, "url") != "https://www.apache.org/licenses/LICENSE-2.0.txt":
        raise ValidationError(f"{path}: missing Apache-2.0 POM license URL")
    issue_management = child(project, "issueManagement")
    if child_text(issue_management, "system") != "github" or child_text(issue_management, "url") != f"{FORK_URL}/issues":
        raise ValidationError(f"{path}: missing fork issue-management metadata")
    scm = child(project, "scm")
    expected_scm = {
        "url": FORK_URL,
        "connection": "scm:git:https://github.com/Leminity/realm-java.git",
        "developerConnection": "scm:git:ssh://git@github.com/Leminity/realm-java.git",
    }
    for name, expected in expected_scm.items():
        if child_text(scm, name) != expected:
            raise ValidationError(f"{path}: missing fork SCM {name}")
    developers = child(project, "developers")
    developer = child(developers, "developer") if developers is not None else None
    if child_text(developer, "id") != "leminity" or child_text(developer, "name") != "Leminity":
        raise ValidationError(f"{path}: missing fork developer metadata")


def validate_repository(repository: Path, root: Path) -> dict[str, object]:
    license_contents, notice_contents = validate_source_notices(root)
    version = (root / "version.txt").read_text(encoding="utf-8").strip()
    if not version:
        raise ValidationError("version.txt is empty")
    report: dict[str, object] = {
        "format": "g010-apache-notice-v1",
        "license_sha256": sha256_bytes(license_contents),
        "notice_sha256": sha256_bytes(notice_contents),
        "version": version,
        "artifacts": {},
    }
    for artifact, extension in ARTIFACTS.items():
        directory = repository / GROUP_PATH / artifact / version
        if not directory.is_dir():
            raise ValidationError(f"missing Maven coordinate directory: {directory}")
        primary = directory / f"{artifact}-{version}.{extension}"
        sources = directory / f"{artifact}-{version}-sources.jar"
        javadoc = directory / f"{artifact}-{version}-javadoc.jar"
        pom = directory / f"{artifact}-{version}.pom"
        for label, path in (("primary", primary), ("sources", sources), ("javadoc", javadoc), ("POM", pom)):
            require_file(path, f"{artifact} {label}")
        validate_pom(pom, artifact, version)
        report["artifacts"][artifact] = {
            "primary": validate_archive(primary, license_contents, notice_contents),
            "sources": validate_archive(sources, license_contents, notice_contents),
            "javadoc": validate_archive(javadoc, license_contents, notice_contents),
            "pom_sha256": sha256_bytes(pom.read_bytes()),
        }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True, help="local Maven-layout repository")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository source root")
    parser.add_argument("--report", type=Path, help="write deterministic JSON report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = validate_repository(args.repository.resolve(), args.root.resolve())
    except ValidationError as error:
        print(f"G010 license verification failed: {error}", file=sys.stderr)
        return 1
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
