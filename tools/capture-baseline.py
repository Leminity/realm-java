#!/usr/bin/env python3
"""Capture the immutable upstream baseline required before production edits."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


EXPECTED_COMMIT = "0ab8d6961afb038d0e0c69478de45dda3958d641"
EXPECTED_TAG = "v10.19.0"
EXPECTED_SUBMODULES = {
    "realm/realm-library/src/main/cpp/realm-core": "5533505d18fda93a7a971d58a191db5005583c92",
    "realm/realm-library/src/main/cpp/realm-core/external/catch": "3f0283de7a9c43200033da996ff9093be3ac84dc",
    "realm/realm-library/src/main/cpp/realm-core/src/external/sha-1": "d9ae30f34095107ece9dceb224839f0dc2f9c1c7",
    "realm/realm-library/src/main/cpp/realm-core/src/external/sha-2": "0e9aebf34101c6aa89355fd76ac9cd886735dee1",
}
ARTIFACT_IDS = [
    "realm-gradle-plugin",
    "realm-transformer",
    "realm-annotations",
    "realm-annotations-processor",
    "realm-android-library",
    "realm-android-kotlin-extensions",
]


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assignment_values(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)=(.*)", line.strip())
        if match:
            result[match.group(1)] = match.group(2)
    return result


def submodules() -> dict[str, str]:
    core = "realm/realm-library/src/main/cpp/realm-core"
    return {
        core: run("git", "rev-parse", f"HEAD:{core}"),
        f"{core}/external/catch": run("git", "-C", core, "rev-parse", "HEAD:external/catch"),
        f"{core}/src/external/sha-1": run("git", "-C", core, "rev-parse", "HEAD:src/external/sha-1"),
        f"{core}/src/external/sha-2": run("git", "-C", core, "rev-parse", "HEAD:src/external/sha-2"),
    }


SOURCE_ROOTS = (
    "gradle-plugin/src",
    "library-build-transformer/src",
    "realm-annotations/src",
    "realm-transformer/src",
    "realm/realm-annotations-processor/src",
    "realm/realm-library/src",
    "realm/kotlin-extensions/src",
)
WRAPPER_PATHS = (
    "gradle/wrapper/gradle-wrapper.properties",
    "examples/gradle/wrapper/gradle-wrapper.properties",
    "gradle-plugin/gradle/wrapper/gradle-wrapper.properties",
    "library-benchmarks/gradle/wrapper/gradle-wrapper.properties",
    "library-build-transformer/gradle/wrapper/gradle-wrapper.properties",
    "realm-annotations/gradle/wrapper/gradle-wrapper.properties",
    "realm-transformer/gradle/wrapper/gradle-wrapper.properties",
    "realm/gradle/wrapper/gradle-wrapper.properties",
)


def source_inventory(root: Path, suffixes: set[str], requires_io_package: bool) -> dict[str, object]:
    # Read the pinned Git tree instead of recursively stat'ing a WSL worktree.
    # Realm Core is represented by one gitlink in the parent tree and therefore
    # cannot accidentally make this source/API inventory traverse its contents.
    output = run("git", "ls-tree", "-r", EXPECTED_COMMIT, "--", *SOURCE_ROOTS)
    files: dict[str, str] = {}
    for line in output.splitlines():
        metadata, path_string = line.split("\t", 1)
        _mode, object_type, object_id = metadata.split()
        path = Path(path_string)
        if (
            object_type == "blob"
            and path.suffix in suffixes
            and (not requires_io_package or "io" in path.parts)
        ):
            files[path_string] = object_id
    return {
        "count": len(files),
        "git_blob_ids": dict(sorted(files.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evidence/provenance/baseline.json")
    args = parser.parse_args()

    root = Path(run("git", "rev-parse", "--show-toplevel"))
    baseline_commit = run("git", "rev-parse", f"{EXPECTED_TAG}^{{commit}}")
    if baseline_commit != EXPECTED_COMMIT:
        raise SystemExit(f"expected {EXPECTED_TAG} to resolve to {EXPECTED_COMMIT}, got {baseline_commit}")
    if subprocess.call(("git", "merge-base", "--is-ancestor", EXPECTED_COMMIT, "HEAD")) != 0:
        raise SystemExit(f"{EXPECTED_COMMIT} is not an ancestor of HEAD")

    actual_submodules = submodules()
    if actual_submodules != EXPECTED_SUBMODULES:
        raise SystemExit(
            "recursive submodule pins differ from the required baseline:\n"
            + json.dumps(actual_submodules, indent=2, sort_keys=True)
        )

    dependencies = assignment_values(root / "dependencies.list")
    wrappers = {}
    for relative_wrapper in WRAPPER_PATHS:
        wrapper = root / relative_wrapper
        wrappers[relative_wrapper] = next(
            line.split("=", 1)[1]
            for line in wrapper.read_text(encoding="utf-8").splitlines()
            if line.startswith("distributionUrl=")
        )

    library_build = (root / "realm/realm-library/build.gradle").read_text(encoding="utf-8")
    abi_match = re.search(r"abiFilters '([^']+)', '([^']+)', '([^']+)', '([^']+)'", library_build)
    if not abi_match:
        raise SystemExit("unable to capture upstream default ABI allowlist")

    manifest = {
        "schema_version": 1,
        "purpose": "immutable pre-production Realm Java v10.19.0 provenance baseline",
        "source": {
            "upstream_remote": run("git", "remote", "get-url", "upstream"),
            "tag": EXPECTED_TAG,
            "commit": baseline_commit,
            "work_branch": run("git", "symbolic-ref", "--short", "HEAD"),
            "fork_remote": run("git", "remote", "get-url", "origin"),
            "fork_discovery": "created after an authenticated Leminity repo-scope authorization check",
        },
        "submodules": actual_submodules,
        "toolchain_pins": {
            key: dependencies[key]
            for key in ("REALM_CORE", "GRADLE_BUILD_TOOLS", "gradle", "ndkVersion", "CMAKE", "KOTLIN")
        },
        "wrappers": wrappers,
        "publication_baseline": {
            "official_group": "io.realm",
            "official_version": (root / "version.txt").read_text(encoding="utf-8").strip(),
            "artifact_ids": ARTIFACT_IDS,
        },
        "native_abi_baseline": list(abi_match.groups()),
        "source_integrity": {
            "dependencies_list_sha256": sha256(root / "dependencies.list"),
            "version_txt_sha256": sha256(root / "version.txt"),
            "public_java_kotlin_sources": source_inventory(root, {".java", ".kt"}, True),
            "android_resources": source_inventory(root, {".xml"}, False),
        },
    }
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
