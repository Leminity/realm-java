#!/usr/bin/env python3
# Modified by Leminity from the upstream Realm Java project.
"""Generate and verify G011 baseline and runtime provenance manifests.

The committed baseline binds immutable tracked source/evidence inputs without
trying to predict the commit that will contain the manifest.  Runtime mode is
separate: it binds the exact checked-out HEAD and a freshly checksummed CI
evidence directory after every required gate has completed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


EXPECTED_BASELINE_COMMIT = "a3203f001e6bda3ff45ca5315bf09c7cba8cb9c6"
EXPECTED_CORE_COMMIT = "a5b7ed7bb8f0db4d362c7e45b2f38358a4aeab47"
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
EXPECTED_CORE_SUBMODULE_PATHS = ("external/catch", "src/external/sha-1", "src/external/sha-2")
RUNTIME_CHECKSUM_MANIFEST = "SHA256SUMS"
RUNTIME_CHECKSUM_LOG = "checksum-verify.log"

GATE_PATHS = (
    ".github/workflows/ci.yml",
    ".github/workflows/pull-request.yml",
    ".github/workflows/release.yml",
    "tools/publish_release.sh",
    "tools/g008-publication.py",
    "tools/test-g008-publication.py",
    "tools/g011-consume-six.sh",
    "tools/test-g011-consume-six.py",
    "tools/g011-verify-native-elf.sh",
    "tools/test-g011-verify-native-elf.py",
    "compatibility-fixtures/ac07-bidirectional/run-ac07.sh",
    "compatibility-fixtures/ac07-bidirectional/verify-ac07-results.py",
    "compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh",
    "tools/test-ac08-g011-parameterization.py",
    "tools/central-portal.py",
    "tools/test-central-portal.py",
    "tools/verify-g003-independent-builds.sh",
    "tools/test-verify-g003-independent-builds.sh",
    "tools/verify-g004-transformer-public-api.sh",
    "tools/test-verify-g004-transformer-public-api.sh",
    "gradle-plugin/src/main/kotlin/io/realm/gradle/Realm.kt",
    "gradle-plugin/src/test/groovy/io/realm/gradle/PluginTest.groovy",
    "tools/verify-g009-ac09-compatibility.py",
    "tools/test-verify-g009-ac09-compatibility.py",
    "tools/verify-g010-license.py",
    "tools/verify-g010-scope.py",
    "tools/test-verify-g010-license.py",
    "tools/test-verify-g010-scope.py",
    "tools/verify-toolchain.sh",
    "tools/g011-evidence-manifest.py",
    "tools/test-g011-evidence-manifest.py",
    "tools/test-g013-workflow-trust.py",
    "tools/test-g014-release-binding.py",
)

RUNTIME_REQUIRED_EXACT = (
    "toolchain/verification.txt",
    "device/preflight.txt",
    "provenance/baseline-verify.log",
    "provenance/manifest-unit.log",
    "ac07/RESULT.txt",
    "ac07/fork-modified/fork-report.json",
    "ac07/logs/fork-instrumentation.log",
    "ac07/logs/official-reverse-instrumentation.log",
    "ac07/original/immutable-input.sha256",
    "ac07/original/immutable-input-after.sha256",
    "ac07/logs/immutable-input-diff.log",
    "g003/gate.log",
    "g004/gate.log",
    "g005/gate.log",
    "g008/build.log",
    "g008/publication-verify.log",
    "g008/publication-manifest.json",
    "g008/maven-central-bundle.zip",
    "g008/unit.log",
    "consumer/result.txt",
    "native/report.txt",
    "g009/official-resolver.log",
    "g009/report.json",
    "g009/unit.log",
    "g010/scope-report.json",
    "g010/scope-unit.log",
    "g010/license-report.json",
    "g010/license-unit.log",
    "portal/unit.log",
    "portal/g014-release-binding-unit.log",
)
RUNTIME_REQUIRED_PREFIXES = ("g003/matrix/", "g005/test-results/", "ac08/", "g008/staging/")


class ManifestError(RuntimeError):
    """Raised when a provenance input violates an exactness invariant."""


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
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def sha256_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def parse_assignments(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)=(.*)", line.strip())
        if match:
            values[match.group(1)] = match.group(2)
    return values


def parse_wrappers(root: Path) -> dict[str, dict[str, str]]:
    paths = (
        "examples/gradle/wrapper/gradle-wrapper.properties",
        "gradle-plugin/gradle/wrapper/gradle-wrapper.properties",
        "gradle/wrapper/gradle-wrapper.properties",
        "library-benchmarks/gradle/wrapper/gradle-wrapper.properties",
        "library-build-transformer/gradle/wrapper/gradle-wrapper.properties",
        "realm-annotations/gradle/wrapper/gradle-wrapper.properties",
        "realm-transformer/gradle/wrapper/gradle-wrapper.properties",
        "realm/gradle/wrapper/gradle-wrapper.properties",
    )
    wrappers: dict[str, dict[str, str]] = {}
    for relative in paths:
        lines = (root / relative).read_text(encoding="utf-8").splitlines()
        url = next(line.split("=", 1)[1] for line in lines if line.startswith("distributionUrl="))
        sha = next(line.split("=", 1)[1] for line in lines if line.startswith("distributionSha256Sum="))
        wrappers[relative] = {"distribution_url": url, "distribution_sha256": sha}
    return wrappers


def parse_build_gradle(root: Path) -> dict[str, object]:
    realm_build = (root / "realm/build.gradle").read_text(encoding="utf-8")
    library_build = (root / "realm/realm-library/build.gradle").read_text(encoding="utf-8")
    abi_match = re.search(r"abiFilters '([^']+)', '([^']+)', '([^']+)'", library_build)
    min_sdk = re.search(r"project\.ext\.minSdkVersion\s*=\s*(\d+)", realm_build)
    compile_sdk = re.search(r"project\.ext\.compileSdkVersion\s*=\s*(\d+)", realm_build)
    target_sdk = re.search(r"project\.ext\.targetSdkVersion\s*=\s*(\d+)", realm_build)
    if not (abi_match and min_sdk and compile_sdk and target_sdk):
        raise ManifestError("unable to capture exact SDK/ABI pins")
    return {
        "min_sdk": int(min_sdk.group(1)),
        "compile_sdk": int(compile_sdk.group(1)),
        "target_sdk": int(target_sdk.group(1)),
        "default_abis": list(abi_match.groups()),
    }


def parse_runtime_fingerprint(root: Path) -> dict[str, object]:
    runtime = root / EXPECTED_TOOLCHAIN_DIR / "emulator-final-runtime.txt"
    environment = root / EXPECTED_TOOLCHAIN_DIR / "environment-diagnostics.txt"
    if not runtime.is_file() or not environment.is_file():
        raise ManifestError("missing checked-in WSL runtime evidence")
    values: dict[str, str] = {}
    for line in runtime.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith(" "):
            key, value = line.split("=", 1)
            values[key] = value
    env_text = environment.read_text(encoding="utf-8")
    return {
        "timestamp": values.get("timestamp", ""),
        "sdk": int(values.get("sdk", "0")),
        "page_size": int(values.get("page_size", "0")),
        "model": values.get("model", ""),
        "build_fingerprint": values.get("build_fingerprint", ""),
        "host_uname": next((line for line in env_text.splitlines() if line.startswith("Linux ")), ""),
        "java_version_line": next((line for line in env_text.splitlines() if line.startswith("openjdk version ")), ""),
        "runtime_sha256": sha256_file(runtime),
        "environment_sha256": sha256_file(environment),
    }


def gitlink_sha(root: Path, relative_path: Path) -> str:
    fields = run_git(root, "ls-tree", "HEAD", relative_path.as_posix()).split()
    if len(fields) < 3:
        raise ManifestError(f"missing gitlink {relative_path}")
    return fields[2]


def core_git_dir(root: Path) -> Path:
    common = Path(run_git(root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = root / common
    git_dir = common / "modules" / EXPECTED_CORE_PATH
    if not git_dir.is_dir():
        raise ManifestError(f"missing Realm Core object store: {git_dir}")
    return git_dir


def run_core_git(root: Path, *args: str) -> str:
    git_dir = core_git_dir(root)
    completed = subprocess.run(
        ["git", f"--git-dir={git_dir}", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode:
        raise ManifestError(f"Realm Core git {' '.join(args)}: {completed.stderr.strip()}")
    return completed.stdout.strip()


def exact_core_submodules(root: Path) -> dict[str, str]:
    commits: dict[str, str] = {}
    for relative in EXPECTED_CORE_SUBMODULE_PATHS:
        commits[relative] = run_core_git(root, "rev-parse", f"{EXPECTED_CORE_COMMIT}:{relative}")
    return commits


def assert_runtime_source_clean(root: Path) -> None:
    tracked_status = run_git(
        root, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=untracked"
    )
    if tracked_status:
        raise ManifestError("runtime source has tracked or staged changes and cannot bind exact HEAD")


def tracked_files(root: Path, relative_dir: Path) -> tuple[str, ...]:
    return tuple(
        line for line in run_git(root, "ls-files", "--", relative_dir.as_posix()).splitlines() if line
    )


def tree_digest(root: Path, relative_dir: Path) -> dict[str, object]:
    directory = root / relative_dir
    if not directory.is_dir():
        raise ManifestError(f"missing evidence directory: {relative_dir}")
    expected = tracked_files(root, relative_dir)
    missing = [relative for relative in expected if not (root / relative).is_file()]
    if missing:
        raise ManifestError(f"missing tracked evidence files: {missing}")
    files = {relative: sha256_file(root / relative) for relative in sorted(expected)}
    tree_hash = sha256_bytes(
        "\n".join(f"{path}\0{digest}" for path, digest in files.items()).encode("utf-8")
    )
    return {
        "directory": relative_dir.as_posix(),
        "file_count": len(files),
        "tree_sha256": tree_hash,
        "files": files,
    }


def parse_checksum_manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", line)
        if not match:
            raise ManifestError(f"invalid checksum manifest line: {line!r}")
        relative = match.group(2).removeprefix("./")
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            raise ManifestError(f"unsafe checksum path: {relative!r}")
        if relative in entries:
            raise ManifestError(f"duplicate checksum path: {relative}")
        entries[relative] = match.group(1)
    if not entries:
        raise ManifestError("runtime checksum manifest is empty")
    return entries


def runtime_evidence_digest(evidence_dir: Path) -> dict[str, object]:
    directory = evidence_dir.resolve()
    manifest = directory / RUNTIME_CHECKSUM_MANIFEST
    verify_log = directory / RUNTIME_CHECKSUM_LOG
    if not directory.is_dir() or not manifest.is_file() or not verify_log.is_file():
        raise ManifestError("runtime evidence requires SHA256SUMS and checksum-verify.log")
    entries = parse_checksum_manifest(manifest)
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name not in {RUNTIME_CHECKSUM_MANIFEST, RUNTIME_CHECKSUM_LOG}
        and not path.name.startswith(".SHA256SUMS") and not path.name.startswith(".checksum-verify")
    }
    if actual != set(entries):
        raise ManifestError(
            f"runtime checksum coverage differs: missing={sorted(actual - set(entries))}, "
            f"stale={sorted(set(entries) - actual)}"
        )
    for relative, expected in entries.items():
        actual_digest = sha256_file(directory / relative)
        if actual_digest != expected:
            raise ManifestError(f"runtime evidence checksum mismatch: {relative}")
    missing_exact = [relative for relative in RUNTIME_REQUIRED_EXACT if relative not in entries]
    if missing_exact:
        raise ManifestError(f"runtime evidence lacks required files: {missing_exact}")
    missing_prefixes = [prefix for prefix in RUNTIME_REQUIRED_PREFIXES if not any(p.startswith(prefix) for p in entries)]
    if missing_prefixes:
        raise ManifestError(f"runtime evidence lacks required trees: {missing_prefixes}")
    canonical = "\n".join(f"{path}\0{entries[path]}" for path in sorted(entries)).encode("utf-8")
    return {
        "directory_name": directory.name,
        "file_count": len(entries),
        "tree_sha256": sha256_bytes(canonical),
        "checksum_manifest_sha256": sha256_file(manifest),
        "checksum_verified": True,
        "required_exact": list(RUNTIME_REQUIRED_EXACT),
        "required_prefixes": list(RUNTIME_REQUIRED_PREFIXES),
        "files": dict(sorted(entries.items())),
    }


def gate_digests(root: Path) -> dict[str, str]:
    missing = [relative for relative in GATE_PATHS if not (root / relative).is_file()]
    if missing:
        raise ManifestError(f"missing gate sources: {missing}")
    return {relative: sha256_file(root / relative) for relative in GATE_PATHS}


def build_manifest(root: Path, mode: str = "baseline", runtime_evidence_dir: Path | None = None) -> dict[str, object]:
    if mode not in {"baseline", "runtime"}:
        raise ManifestError(f"unsupported manifest mode: {mode}")
    root = root.resolve()
    if mode == "runtime":
        if runtime_evidence_dir is None:
            raise ManifestError("runtime mode requires --runtime-evidence-dir")
        assert_runtime_source_clean(root)
    if not git_succeeds(root, "merge-base", "--is-ancestor", EXPECTED_BASELINE_COMMIT, "HEAD"):
        raise ManifestError(f"baseline {EXPECTED_BASELINE_COMMIT} is not an ancestor of HEAD")

    dependencies = parse_assignments(root / "dependencies.list")
    wrappers = parse_wrappers(root)
    build_gradle = parse_build_gradle(root)
    wsl = parse_runtime_fingerprint(root)
    core_gitlink = gitlink_sha(root, EXPECTED_CORE_PATH)
    core_commit = core_gitlink
    if core_gitlink != EXPECTED_CORE_COMMIT:
        raise ManifestError(f"unexpected Core gitlink: {core_gitlink}")
    run_core_git(root, "cat-file", "-e", f"{EXPECTED_CORE_COMMIT}^{{commit}}")
    if subprocess.run(
        [
            "git",
            f"--git-dir={core_git_dir(root)}",
            "merge-base",
            "--is-ancestor",
            EXPECTED_CORE_PREREQUISITE,
            EXPECTED_CORE_COMMIT,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode:
        raise ManifestError("Core prerequisite is not an ancestor")

    expected_dependencies = {
        "GRADLE_BUILD_TOOLS": EXPECTED_AGP,
        "gradle": EXPECTED_GRADLE,
        "ndkVersion": EXPECTED_NDK,
        "CMAKE": EXPECTED_CMAKE,
    }
    for name, expected in expected_dependencies.items():
        if dependencies.get(name) != expected:
            raise ManifestError(f"unexpected {name}: {dependencies.get(name)!r}")
    if (build_gradle["min_sdk"], build_gradle["compile_sdk"], build_gradle["target_sdk"]) != (
        EXPECTED_MIN_SDK, EXPECTED_COMPILE_SDK, EXPECTED_TARGET_SDK
    ):
        raise ManifestError("unexpected Android SDK pins")
    if set(build_gradle["default_abis"]) != EXPECTED_ABIS:
        raise ManifestError(f"unexpected ABI allowlist: {build_gradle['default_abis']}")
    if (wsl["sdk"], wsl["page_size"], wsl["model"]) != (
        EXPECTED_DEVICE_SDK, EXPECTED_DEVICE_PAGE_SIZE, EXPECTED_DEVICE_MODEL
    ):
        raise ManifestError("unexpected checked-in API37/16KiB runtime fingerprint")
    for relative, wrapper in wrappers.items():
        if wrapper != {
            "distribution_url": EXPECTED_GRADLE_URL.replace(":", "\\:", 1),
            "distribution_sha256": EXPECTED_GRADLE_SHA256,
        }:
            raise ManifestError(f"unexpected wrapper pin: {relative}")

    source: dict[str, object] = {
        "baseline_root_commit": EXPECTED_BASELINE_COMMIT,
        "core_commit": core_commit,
        "core_gitlink": core_gitlink,
        "core_submodules": exact_core_submodules(root),
    }
    if mode == "runtime":
        source["current_head_commit"] = run_git(root, "rev-parse", "HEAD")

    manifest: dict[str, object] = {
        "schema_version": 2,
        "manifest_kind": mode,
        "purpose": "G011 reproducible source, WSL, CI and protected-release provenance",
        "source": source,
        "toolchain": {
            "java_major": EXPECTED_JAVA_MAJOR,
            "gradle_version": EXPECTED_GRADLE,
            "agp_version": EXPECTED_AGP,
            "compile_sdk": EXPECTED_COMPILE_SDK,
            "target_sdk": EXPECTED_TARGET_SDK,
            "min_sdk": EXPECTED_MIN_SDK,
            "ndk_version": EXPECTED_NDK,
            "cmake_version": EXPECTED_CMAKE,
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
        "wsl": wsl,
        "evidence": {
            "toolchain_android17_wsl2": tree_digest(root, EXPECTED_TOOLCHAIN_DIR),
            "oracle_official_10_19_0": tree_digest(root, EXPECTED_ORACLE_DIR),
        },
        "gate_digests": gate_digests(root),
        "assertions": {
            "supported_release_graph": True,
            "six_artifact_publication_gate": True,
            "page_size_16384_fixture": True,
            "no_x86": True,
            "elf_min_alignment_bytes": EXPECTED_ELF_MIN_ALIGNMENT,
        },
    }
    if mode == "runtime":
        manifest["ci"] = runtime_evidence_digest(runtime_evidence_dir)
    return manifest


def canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mode", choices=("baseline", "runtime"), default="baseline")
    parser.add_argument("--runtime-evidence-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.mode == "baseline" and args.runtime_evidence_dir is not None:
        print("G011 manifest failed: baseline mode forbids --runtime-evidence-dir", file=sys.stderr)
        return 1
    try:
        manifest = build_manifest(args.root, args.mode, args.runtime_evidence_dir)
        rendered = canonical_json(manifest)
        if args.verify is not None and args.verify.resolve().read_text(encoding="utf-8") != rendered:
            raise ManifestError(f"manifest mismatch: {args.verify}")
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_name(f".{args.output.name}.tmp")
            temporary.write_text(rendered, encoding="utf-8")
            temporary.replace(args.output)
        elif args.verify is None:
            print(rendered, end="")
    except (ManifestError, OSError, ValueError) as error:
        print(f"G011 manifest failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
