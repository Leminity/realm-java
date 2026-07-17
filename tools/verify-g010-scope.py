#!/usr/bin/env python3
"""Verify G010's ledger-bound local-release scope without executing Gradle."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


BASELINE_TAG = "v10.19.0"
BASELINE_CORE = "5533505d18fda93a7a971d58a191db5005583c92"
EXPECTED_CORE = "d7b52ccbada0283527db36143cfeab18692b4ed0"
CORE_PATH = "realm/realm-library/src/main/cpp/realm-core"
CORE_TOOLCHAIN_PREREQUISITE = "b741862e7ca7cb1b81d276457989067b7737dc86"
CORE_TOOLCHAIN_PREREQUISITE_PATH = "src/external/s2/base/macros.h"
RETIRED_PROCESSOR_EVIDENCE = "tools/verify-g009-ac09-compatibility.py"

# These are the only non-fixture production source deltas from v10.19.0.
# Their ledger keys deliberately name the reproduced failure, not a task order.
SOURCE_APPROVALS = {
    "gradle-plugin/src/main/kotlin/io/realm/gradle/Realm.kt": "G004-F001",
    "library-build-transformer/src/main/kotlin/io/realm/buildtransformer/RealmBuildTransformer.kt": "G004-F001",
    "realm-transformer/src/main/kotlin/io/realm/transformer/RealmTransformer.kt": "G004-F001",
    "realm-transformer/src/main/kotlin/io/realm/transformer/ext/ProjectExt.kt": "G004-F001",
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/RealmProcessor.kt": "RealmVersionChecker",
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/RealmVersionChecker.kt": "RealmVersionChecker",
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/CamelCaseConverter.kt": "F053",
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/LowerCaseWithSeparatorConverter.kt": "F053",
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/PascalCaseConverter.kt": "F053",
}

BUILD_APPROVALS = {
    "build.gradle": "F030",
    "dependencies.list": "F017",
    "gradle-plugin/build.gradle": "F035",
    "library-build-transformer/build.gradle": "F011",
    "mavencentral-properties.gradle": "G008-PUB-001",
    "mavencentral-publications.gradle": "G008-PUB-001",
    "mavencentral-publish.gradle": "G008-PUB-001",
    "realm-annotations/build.gradle": "F001",
    "realm-transformer/build.gradle": "F005",
    "realm/build.gradle": "F014",
    "realm/kotlin-extensions/build.gradle": "F021",
    "realm/realm-annotations-processor/build.gradle": "F024",
    "realm/realm-library/build.gradle": "F019",
    "version.txt": "G008-PUB-001",
    "examples/gradle/wrapper/gradle-wrapper.properties": "F017",
    "gradle-plugin/gradle/wrapper/gradle-wrapper.properties": "F017",
    "gradle/wrapper/gradle-wrapper.properties": "F017",
    "library-benchmarks/gradle/wrapper/gradle-wrapper.properties": "F017",
    "library-build-transformer/gradle/wrapper/gradle-wrapper.properties": "F017",
    "realm-annotations/gradle/wrapper/gradle-wrapper.properties": "F017",
    "realm-transformer/gradle/wrapper/gradle-wrapper.properties": "F017",
    "realm/gradle/wrapper/gradle-wrapper.properties": "F017",
}

CORE_APPROVED_PATHS = {
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
}
CORE_EXPECTED_PATHS = CORE_APPROVED_PATHS | {CORE_TOOLCHAIN_PREREQUISITE_PATH}

# The two processor changes remove the retired checker and its static update URL.
# G009's verifier is the durable acceptance evidence for that deletion; it is not
# a compatibility ledger failure-id because it was a supported-graph removal.
RETIRED_PROCESSOR_PATHS = {
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/RealmProcessor.kt",
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/RealmVersionChecker.kt",
}

SUPPORTED_GRAPH_FILES = tuple(BUILD_APPROVALS) + ("dependencies.list",)
FORBIDDEN_EXECUTION = re.compile(
    r"(?:ossrh|oss\.sonatype|s3\.amazonaws|static\.realm\.io|"
    r"org\.gradle\.internal|com\.android\.build\.gradle\.internal|"
    r"AndroidArtifacts|BaseExtension)",
    re.IGNORECASE,
)
FORBIDDEN_RUNTIME = re.compile(
    r"(?:static\.realm\.io|oss\.sonatype|s3\.amazonaws|"
    r"ObjectServerFacade|io\.realm\.mongodb\.(?:sync|App|User)|"
    r"org\.gradle\.internal|com\.android\.build\.gradle\.internal)",
    re.IGNORECASE,
)
SOURCE_SUFFIXES = {".kt", ".java", ".c", ".cpp", ".h"}


class VerificationError(RuntimeError):
    pass


def run(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode:
        raise VerificationError(f"git {' '.join(args)}: {completed.stderr.strip()}")
    return completed.stdout


def git_succeeds(root: Path, *args: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def changed_paths(root: Path, base: str, head: str) -> list[str]:
    paths: list[str] = []
    for line in run(root, "diff", "--name-status", f"{base}..{head}").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            paths.append(fields[-1])  # rename/copy destinations are the released paths
    return sorted(set(paths))


def is_product_source(path: str) -> bool:
    candidate = Path(path)
    if candidate.suffix not in SOURCE_SUFFIXES:
        return False
    text = candidate.as_posix()
    return not (
        text.startswith(("compatibility-fixtures/", "evidence/", "tools/"))
        or "/src/test/" in text
        or "/src/androidTest/" in text
        or "/generated-jni-headers/" in text
    )


def is_build_or_publication(path: str) -> bool:
    return path in BUILD_APPROVALS


def code_lines(path: Path) -> list[tuple[int, str]]:
    """Return executable-looking lines; full-line comments are archival prose."""
    lines = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "#", "*", "/*")):
            continue
        lines.append((number, line))
    return lines


def numstat_paths(
    root: Path,
    base: str,
    head: str,
    ignore_space: bool = False,
    paths: tuple[str, ...] = (),
) -> set[str]:
    args = ["diff"]
    if ignore_space:
        args.append("-w")
    args.extend(["--numstat", f"{base}..{head}"])
    if paths:
        args.extend(["--", *paths])
    paths = set()
    for line in run(root, *args).splitlines():
        fields = line.split("\t")
        if len(fields) >= 3:
            paths.add(fields[-1])
    return paths


def core_paths(root: Path, base_core: str) -> tuple[str, list[str]]:
    core = root / CORE_PATH
    head = run(core, "rev-parse", "HEAD").strip()
    paths = [line.split("\t")[-1] for line in run(core, "diff", "--name-status", f"{base_core}..{head}").splitlines()]
    return head, sorted(set(paths))


def retired_processor_approval(root: Path) -> bool:
    evidence = root / RETIRED_PROCESSOR_EVIDENCE
    if not evidence.is_file():
        return False
    text = evidence.read_text(encoding="utf-8")
    return all(
        f'"{path}": "retired checker removal"' in text
        for path in RETIRED_PROCESSOR_PATHS
    ) and "RETIRED_PROCESSOR_BYTECODE_STRINGS" in text


def verify(root: Path, base: str, head: str) -> dict:
    failures: list[str] = []
    ledger = (root / "compatibility-change-ledger.md").read_text(encoding="utf-8")
    production_ledger = (root / "production-diff-ledger.md").read_text(encoding="utf-8")
    paths = changed_paths(root, base, head)
    sources = sorted(path for path in paths if is_product_source(path))
    builds = sorted(path for path in paths if is_build_or_publication(path))
    approved_release_paths = tuple(sorted(set(SOURCE_APPROVALS) | set(BUILD_APPROVALS)))
    whitespace_only = numstat_paths(root, base, head, paths=approved_release_paths) - numstat_paths(
        root, base, head, ignore_space=True, paths=approved_release_paths
    )

    if "Future production changes must reference a `failure-id`" not in production_ledger:
        failures.append("production diff ledger lacks the failure-id boundary")
    if set(sources) != set(SOURCE_APPROVALS):
        failures.append(f"unledgered production source diff: expected {sorted(SOURCE_APPROVALS)}, got {sources}")
    if set(builds) != set(BUILD_APPROVALS):
        failures.append(f"unledgered build/publication diff: expected {sorted(BUILD_APPROVALS)}, got {builds}")
    retirement_approved = retired_processor_approval(root)
    for path, token in {**SOURCE_APPROVALS, **BUILD_APPROVALS}.items():
        if path in RETIRED_PROCESSOR_PATHS:
            if not retirement_approved:
                failures.append(f"retired processor evidence missing for {path}")
            if path in whitespace_only:
                failures.append(f"formatting-only cleanup is forbidden: {path}")
            continue
        if token not in ledger:
            failures.append(f"ledger token {token} missing for {path}")
        if path in whitespace_only:
            failures.append(f"formatting-only cleanup is forbidden: {path}")

    base_core = run(root, "ls-tree", base, CORE_PATH).split()[2]
    core_head, actual_core_paths = core_paths(root, base_core)
    if base_core != BASELINE_CORE:
        failures.append(f"unexpected baseline Core gitlink {base_core}")
    if core_head != EXPECTED_CORE:
        failures.append(f"unexpected Core revision {core_head}")
    core = root / CORE_PATH
    prerequisite_paths = changed_paths(core, BASELINE_CORE, CORE_TOOLCHAIN_PREREQUISITE)
    backport_paths = changed_paths(core, CORE_TOOLCHAIN_PREREQUISITE, core_head)
    prerequisite_valid = (
        git_succeeds(core, "merge-base", "--is-ancestor", CORE_TOOLCHAIN_PREREQUISITE, core_head)
        and prerequisite_paths == [CORE_TOOLCHAIN_PREREQUISITE_PATH]
    )
    if not prerequisite_valid:
        failures.append(
            "Core toolchain prerequisite is not the verified one-file b741862 delta: "
            f"{prerequisite_paths}"
        )
    if set(backport_paths) != CORE_APPROVED_PATHS:
        failures.append(
            "Core encrypted-page portability backport paths differ from c970 scope: "
            f"expected {sorted(CORE_APPROVED_PATHS)}, got {backport_paths}"
        )
    if set(actual_core_paths) != CORE_EXPECTED_PATHS:
        failures.append(f"unledgered Core paths: {sorted(set(actual_core_paths) ^ CORE_EXPECTED_PATHS)}")

    forbidden_hits: list[str] = []
    for relative in SUPPORTED_GRAPH_FILES:
        path = root / relative
        if not path.is_file():
            failures.append(f"supported graph file missing: {relative}")
            continue
        for number, line in code_lines(path):
            if FORBIDDEN_EXECUTION.search(line):
                forbidden_hits.append(f"{relative}:{number}:{line.strip()}")
    if forbidden_hits:
        failures.append("forbidden supported-graph execution reference: " + " | ".join(forbidden_hits))

    runtime_hits: list[str] = []
    for relative in sources:
        path = root / relative
        if not path.is_file():  # the approved RealmVersionChecker deletion is intentional
            continue
        for number, line in code_lines(path):
            if FORBIDDEN_RUNTIME.search(line):
                runtime_hits.append(f"{relative}:{number}:{line.strip()}")
    if runtime_hits:
        failures.append("forbidden runtime reference in changed product source: " + " | ".join(runtime_hits))

    library_build = (root / "realm/realm-library/build.gradle").read_text(encoding="utf-8")
    kotlin_build = (root / "realm/kotlin-extensions/build.gradle").read_text(encoding="utf-8")
    archival_markers = {
        "realm-library ObjectServer source retained": "src/objectServer" in library_build,
        "realm-library ObjectServer variants disabled": "beforeVariants" in library_build and "objectServer" in library_build,
        "kotlin extensions ObjectServer source retained": "src/objectServer" in kotlin_build,
        "kotlin extensions ObjectServer variants disabled": "beforeVariants" in kotlin_build and "objectServer" in kotlin_build,
    }
    missing_archival = [name for name, present in archival_markers.items() if not present]
    if missing_archival:
        failures.append("archival Sync/ObjectServer boundary lost: " + ", ".join(missing_archival))

    return {
        "base": run(root, "rev-parse", base).strip(),
        "head": run(root, "rev-parse", head).strip(),
        "core": {
            "base": base_core,
            "head": core_head,
            "changed_paths": actual_core_paths,
            "toolchain_prerequisite": {
                "commit": CORE_TOOLCHAIN_PREREQUISITE,
                "paths": prerequisite_paths,
                "valid": prerequisite_valid,
            },
            "encrypted_page_backport_paths": backport_paths,
        },
        "changed": {"all_count": len(paths), "product_sources": sources, "build_publication": builds},
        "archival_sync_boundary": archival_markers,
        "retired_processor_evidence": retirement_approved,
        "forbidden_supported_graph_hits": forbidden_hits,
        "forbidden_runtime_hits": runtime_hits,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base", default=BASELINE_TAG)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--write-report", type=Path)
    args = parser.parse_args()
    report = verify(args.root.resolve(), args.base, args.head)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.write_report:
        args.write_report.parent.mkdir(parents=True, exist_ok=True)
        args.write_report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
