#!/usr/bin/env python3
"""Generate and verify the deterministic G011 source/evidence manifest.

The manifest binds the isolated worker worktree provenance to the pinned
toolchain and the checked-in evidence trail.  CI uses the same helper to
recompute the manifest and compare it against the committed JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


EXPECTED_ROOT_COMMIT = "db46419888e6c63230e5563bce6862c2de674b6b"
EXPECTED_CURRENT_HEAD_COMMIT = "0de73ccbb4a8b42eabb475eca05f94b3599c38bc"
EXPECTED_CORE_COMMIT = "d7b52ccbada0283527db36143cfeab18692b4ed0"
EXPECTED_CORE_PREREQUISITE = "b741862e7ca7cb1b81d276457989067b7737dc86"
EXPECTED_GRADLE_URL = "https://services.gradle.org/distributions/gradle-9.6.1-bin.zip"
EXPECTED_GRADLE_SHA256 = "9c0f7faeeb306cb14e4279a3e084ca6b596894089a0638e68a07c945a32c9e14"
EXPECTED_AGP = "9.1.1"
EXPECTED_GRADLE = "9.6.1"
EXPECTED_JAVA_MAJOR = 17
EXPECTED_MIN_SDK = 21
EXPECTED_COMPILE_SDK = 37
EXPECTED_TARGET_SDK = 37
EXPECTED_NDK = "29.0.14206865"
EXPECTED_CMAKE = "3.27.7"
EXPECTED_ABIS = frozenset(("arm64-v8a", "armeabi-v7a", "x86_64"))
EXPECTED_DEVICE_MODEL = "sdk_gphone16k_x86_64"
EXPECTED_DEVICE_PAGE_SIZE = 16384
EXPECTED_DEVICE_SDK = 37
EXPECTED_ELF_MIN_ALIGNMENT = 0x4000
EXPECTED_TOOLCHAIN_DIR = Path("evidence/toolchain/android17-wsl2")
EXPECTED_ORACLE_DIR = Path("evidence/oracle/official-10.19.0")
EXPECTED_CORE_PATH = Path("realm/realm-library/src/main/cpp/realm-core")
IGNORED_DIGEST_PARTS = frozenset(
    {
        ".gradle",
        "build",
        "download",
        "downloads",
        "extraction",
        "extracted",
        "SHA256SUMS",
        "checksum-verify.log",
    }
)


class ManifestError(RuntimeError):
    """Raised when the manifest inputs fail an exactness or consistency check."""


def run_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode:
        raise ManifestError(f"git {' '.join(args)}: {completed.stderr.strip()}")
    return completed.stdout.strip()


def git_succeeds(root: Path, *args: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        ).returncode
        == 0
    )


def sha256_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def parse_assignments(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)=(.*)", line.strip())
        if match:
            values[match.group(1)] = match.group(2)
    return values


def parse_wrappers(root: Path) -> dict[str, dict[str, str]]:
    wrappers: dict[str, dict[str, str]] = {}
    wrapper_paths = (
        "examples/gradle/wrapper/gradle-wrapper.properties",
        "gradle-plugin/gradle/wrapper/gradle-wrapper.properties",
        "gradle/wrapper/gradle-wrapper.properties",
        "library-benchmarks/gradle/wrapper/gradle-wrapper.properties",
        "library-build-transformer/gradle/wrapper/gradle-wrapper.properties",
        "realm-annotations/gradle/wrapper/gradle-wrapper.properties",
        "realm-transformer/gradle/wrapper/gradle-wrapper.properties",
        "realm/gradle/wrapper/gradle-wrapper.properties",
    )
    for relative in wrapper_paths:
        content = (root / relative).read_text(encoding="utf-8").splitlines()
        url = next(line.split("=", 1)[1] for line in content if line.startswith("distributionUrl="))
        sha = next(line.split("=", 1)[1] for line in content if line.startswith("distributionSha256Sum="))
        wrappers[relative] = {"distribution_url": url, "distribution_sha256": sha}
    return wrappers


def parse_build_gradle(root: Path) -> dict[str, object]:
    realm_build = (root / "realm/build.gradle").read_text(encoding="utf-8")
    library_build = (root / "realm/realm-library/build.gradle").read_text(encoding="utf-8")
    abi_match = re.search(
        r"abiFilters '([^']+)', '([^']+)', '([^']+)'",
        library_build,
    )
    if not abi_match:
        raise ManifestError("unable to find the default ABI allowlist in realm/realm-library/build.gradle")
    min_sdk = re.search(r"project\.ext\.minSdkVersion\s*=\s*(\d+)", realm_build)
    compile_sdk = re.search(r"project\.ext\.compileSdkVersion\s*=\s*(\d+)", realm_build)
    target_sdk = re.search(r"project\.ext\.targetSdkVersion\s*=\s*(\d+)", realm_build)
    if not (min_sdk and compile_sdk and target_sdk):
        raise ManifestError("unable to capture exact Android SDK pinning from realm/build.gradle")
    return {
        "min_sdk": int(min_sdk.group(1)),
        "compile_sdk": int(compile_sdk.group(1)),
        "target_sdk": int(target_sdk.group(1)),
        "default_abis": list(abi_match.groups()),
    }


def parse_runtime_fingerprint(root: Path) -> dict[str, object]:
    runtime = root / EXPECTED_TOOLCHAIN_DIR / "emulator-final-runtime.txt"
    env = root / EXPECTED_TOOLCHAIN_DIR / "environment-diagnostics.txt"
    if not runtime.is_file() or not env.is_file():
        raise ManifestError("missing required WSL evidence files under evidence/toolchain/android17-wsl2")

    runtime_values: dict[str, str] = {}
    for line in runtime.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith(" "):
            key, value = line.split("=", 1)
            runtime_values[key] = value

    env_text = env.read_text(encoding="utf-8")
    host_line = next((line for line in env_text.splitlines() if line.startswith("Linux ")), "")
    java_line = next((line for line in env_text.splitlines() if line.startswith("openjdk version ")), "")
    return {
        "timestamp": runtime_values.get("timestamp", ""),
        "sdk": int(runtime_values.get("sdk", "0")),
        "page_size": int(runtime_values.get("page_size", "0")),
        "model": runtime_values.get("model", ""),
        "build_fingerprint": runtime_values.get("build_fingerprint", ""),
        "host_uname": host_line,
        "java_version_line": java_line,
        "runtime_sha256": sha256_file(runtime),
        "environment_sha256": sha256_file(env),
    }


def tree_digest(root: Path, relative_dir: Path) -> dict[str, object]:
    directory = root / relative_dir
    if not directory.is_dir():
        raise ManifestError(f"missing evidence directory: {relative_dir}")
    files: dict[str, str] = {}
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if any(part in IGNORED_DIGEST_PARTS for part in path.relative_to(root).parts):
            continue
        files[rel] = sha256_file(path)
    tree_hash = sha256_bytes(
        "\n".join(f"{path}\0{digest}" for path, digest in files.items()).encode("utf-8")
    )
    return {
        "directory": relative_dir.as_posix(),
        "file_count": len(files),
        "tree_sha256": tree_hash,
        "files": files,
    }


def gitlink_sha(root: Path, relative_path: Path) -> str:
    entry = run_git(root, "ls-tree", "HEAD", relative_path.as_posix())
    return entry.split()[2]


def build_manifest(root: Path) -> dict[str, object]:
    dependencies = parse_assignments(root / "dependencies.list")
    wrappers = parse_wrappers(root)
    build_gradle = parse_build_gradle(root)
    runtime = parse_runtime_fingerprint(root)
    toolchain_root = tree_digest(root, EXPECTED_TOOLCHAIN_DIR)
    oracle_root = tree_digest(root, EXPECTED_ORACLE_DIR)
    runtime_head_commit = run_git(root, "rev-parse", "HEAD")
    core_commit = run_git(root, "-C", EXPECTED_CORE_PATH.as_posix(), "rev-parse", "HEAD")
    core_gitlink = gitlink_sha(root, EXPECTED_CORE_PATH)
    core_catch = run_git(root, "-C", EXPECTED_CORE_PATH.as_posix(), "rev-parse", "HEAD:external/catch")
    core_sha1 = run_git(root, "-C", EXPECTED_CORE_PATH.as_posix(), "rev-parse", "HEAD:src/external/sha-1")
    core_sha2 = run_git(root, "-C", EXPECTED_CORE_PATH.as_posix(), "rev-parse", "HEAD:src/external/sha-2")

    if runtime_head_commit != EXPECTED_CURRENT_HEAD_COMMIT:
        raise ManifestError(
            f"unexpected current worktree HEAD {runtime_head_commit}; expected {EXPECTED_CURRENT_HEAD_COMMIT}"
        )
    if core_commit != EXPECTED_CORE_COMMIT or core_gitlink != EXPECTED_CORE_COMMIT:
        raise ManifestError(
            f"unexpected core commit {core_commit} / gitlink {core_gitlink}; expected {EXPECTED_CORE_COMMIT}"
        )
    if not git_succeeds(root, "-C", EXPECTED_CORE_PATH.as_posix(), "merge-base", "--is-ancestor", EXPECTED_CORE_PREREQUISITE, "HEAD"):
        raise ManifestError("core prerequisite commit is not an ancestor of the current core HEAD")

    if dependencies.get("GRADLE_BUILD_TOOLS") != EXPECTED_AGP:
        raise ManifestError(f"unexpected AGP pin {dependencies.get('GRADLE_BUILD_TOOLS')!r}")
    if dependencies.get("gradle") != EXPECTED_GRADLE:
        raise ManifestError(f"unexpected Gradle pin {dependencies.get('gradle')!r}")
    if dependencies.get("ndkVersion") != EXPECTED_NDK:
        raise ManifestError(f"unexpected NDK pin {dependencies.get('ndkVersion')!r}")
    if dependencies.get("CMAKE") != EXPECTED_CMAKE:
        raise ManifestError(f"unexpected CMake pin {dependencies.get('CMAKE')!r}")
    if build_gradle["min_sdk"] != EXPECTED_MIN_SDK or build_gradle["compile_sdk"] != EXPECTED_COMPILE_SDK:
        raise ManifestError("unexpected SDK levels in realm/build.gradle")
    if build_gradle["target_sdk"] != EXPECTED_TARGET_SDK:
        raise ManifestError("unexpected target SDK level in realm/build.gradle")
    if set(build_gradle["default_abis"]) != EXPECTED_ABIS:
        raise ManifestError(f"unexpected default ABI allowlist {build_gradle['default_abis']!r}")
    if runtime["sdk"] != EXPECTED_DEVICE_SDK or runtime["page_size"] != EXPECTED_DEVICE_PAGE_SIZE:
        raise ManifestError("unexpected WSL runtime fingerprint")
    if runtime["model"] != EXPECTED_DEVICE_MODEL:
        raise ManifestError("unexpected emulator model in runtime fingerprint")

    return {
        "schema_version": 1,
        "purpose": "G011 reproducible CI and WSL/Linux source evidence manifest",
        "source": {
            "baseline_root_commit": EXPECTED_ROOT_COMMIT,
            "current_head_commit": runtime_head_commit,
            "core_commit": core_commit,
            "core_gitlink": core_gitlink,
            "core_submodules": {
                "external/catch": core_catch,
                "src/external/sha-1": core_sha1,
                "src/external/sha-2": core_sha2,
            },
        },
        "toolchain": {
            "java_major": EXPECTED_JAVA_MAJOR,
            "gradle_version": dependencies["gradle"],
            "agp_version": dependencies["GRADLE_BUILD_TOOLS"],
            "compile_sdk": build_gradle["compile_sdk"],
            "target_sdk": build_gradle["target_sdk"],
            "min_sdk": build_gradle["min_sdk"],
            "ndk_version": dependencies["ndkVersion"],
            "cmake_version": dependencies["CMAKE"],
            "gradle_wrapper_sha256": EXPECTED_GRADLE_SHA256,
            "gradle_wrapper_url": EXPECTED_GRADLE_URL,
            "wrappers": wrappers,
            "release_graph": {
                "supported_abis": sorted(EXPECTED_ABIS),
                "no_x86": True,
                "minimum_elf_alignment": EXPECTED_ELF_MIN_ALIGNMENT,
                "page_size": EXPECTED_DEVICE_PAGE_SIZE,
            },
        },
        "wsl": runtime,
        "evidence": {
            "toolchain_android17_wsl2": toolchain_root,
            "oracle_official_10_19_0": oracle_root,
        },
        "gate_digests": {
            ".github/workflows/ci.yml": sha256_file(root / ".github/workflows/ci.yml"),
            ".github/workflows/release.yml": sha256_file(root / ".github/workflows/release.yml"),
            "compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh": sha256_file(
                root / "compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh"
            ),
            "tools/central-portal.py": sha256_file(root / "tools/central-portal.py"),
            "tools/test-central-portal.py": sha256_file(root / "tools/test-central-portal.py"),
            "tools/verify-g003-independent-builds.sh": sha256_file(root / "tools/verify-g003-independent-builds.sh"),
            "tools/test-verify-g003-independent-builds.sh": sha256_file(root / "tools/test-verify-g003-independent-builds.sh"),
            "tools/verify-g010-license.py": sha256_file(root / "tools/verify-g010-license.py"),
            "tools/verify-g010-scope.py": sha256_file(root / "tools/verify-g010-scope.py"),
            "tools/test-verify-g010-license.py": sha256_file(root / "tools/test-verify-g010-license.py"),
            "tools/test-verify-g010-scope.py": sha256_file(root / "tools/test-verify-g010-scope.py"),
            "tools/verify-toolchain.sh": sha256_file(root / "tools/verify-toolchain.sh"),
            "tools/g008-publication.py": sha256_file(root / "tools/g008-publication.py"),
            "tools/test-g008-publication.py": sha256_file(root / "tools/test-g008-publication.py"),
            "tools/verify-g009-ac09-compatibility.py": sha256_file(root / "tools/verify-g009-ac09-compatibility.py"),
            "tools/test-verify-g009-ac09-compatibility.py": sha256_file(root / "tools/test-verify-g009-ac09-compatibility.py"),
            "tools/g011-evidence-manifest.py": sha256_file(root / "tools/g011-evidence-manifest.py"),
            "tools/test-g011-evidence-manifest.py": sha256_file(root / "tools/test-g011-evidence-manifest.py"),
        },
        "assertions": {
            "supported_release_graph": True,
            "six_artifact_publication_gate": True,
            "page_size_16384_fixture": True,
            "no_x86": True,
            "elf_min_alignment_bytes": EXPECTED_ELF_MIN_ALIGNMENT,
        },
    }


def canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="write the generated manifest JSON")
    parser.add_argument("--verify", type=Path, help="compare the generated manifest with an existing JSON file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        manifest = build_manifest(root)
    except ManifestError as error:
        print(f"G011 manifest failed: {error}", file=sys.stderr)
        return 1

    rendered = canonical_json(manifest)
    if args.verify is not None:
        expected = args.verify.resolve().read_text(encoding="utf-8")
        if expected != rendered:
            print(f"G011 manifest mismatch: {args.verify}", file=sys.stderr)
            return 1
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        if args.verify is None:
            print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
