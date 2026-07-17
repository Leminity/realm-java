#!/usr/bin/env python3
"""Verify the supported local Realm release against the 10.19.0 oracle.

The check compares API shape, not archive bytes: toolchain upgrades legitimately
change zip metadata and Maven coordinates, but not public classes, signatures,
or Android resources.
"""

from __future__ import annotations

import argparse
import csv
from functools import cache
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


BASELINE_TAG = "v10.19.0"
OFFICIAL_VERSION = "10.19.0"
FORK_VERSION = "10.19.0-agp9.1"
ARTIFACTS = {
    "realm-gradle-plugin": ".jar",
    "realm-transformer": ".jar",
    "realm-annotations": ".jar",
    "realm-annotations-processor": ".jar",
    "realm-android-library": ".aar",
    "realm-android-kotlin-extensions": ".aar",
}
# F033 confines the supported local release graph to the local database. These
# exact types are absent from its intentionally stripped Sync/ObjectServer API.
UNSUPPORTED_PREFIXES = (
    "io.realm.mongodb.",
    "io.realm.internal.ObjectServerFacade",
    "io.realm.internal.annotations.ObjectServer",
    "io.realm.internal.UnmanagedSubscription",
    "io.realm.internal.objectstore.OsMutableSubscriptionSet",
    "io.realm.internal.objectstore.OsSubscription",
    "io.realm.kotlin.SyncedRealmExtensions",
)
GENERATED_JNI_PREFIX = "realm/realm-library/src/main/cpp/generated-jni-headers/"
# G004-F001 replaces the removed AGP boot-classpath accessor with the public
# lazy SdkComponents provider. The old extension method is intentionally gone.
APPROVED_SIGNATURE_OMISSIONS = {
    "io.realm.transformer.ext.ProjectExtKt": {
        "  public static final java.util.List<java.io.File> getBootClasspath(org.gradle.api.Project);",
    },
}
APPROVED_COMPILER_SIGNATURE_ADDITIONS = {
    "io.realm.processor.Constants$RealmFieldType": {
        "signature": "  public static kotlin.enums.EnumEntries<io.realm.processor.Constants$RealmFieldType> getEntries();",
        "descriptor": "()Lkotlin/enums/EnumEntries;",
    },
}
G006_STABLE_API_DECISION = (
    ".omx/recovery/transactions/G006-base-local-db-library-build-20260716T133354Z/"
    "ac09-stable-api-supersedes-raw-class-inventory-20260716T161100Z/decision.md"
)
# The implementation plan explicitly retires the processor's update checker:
# .omx/plans/realm-java-android17-agp9-mavencentral.md:185 and the companion
# test specification require both public classes and the static.realm.io
# endpoint to be absent. No other public class removal is allowed.
APPROVED_PUBLIC_CLASS_REMOVALS = {
    "realm-annotations-processor": {
        "io.realm.processor.RealmVersionChecker",
        "io.realm.processor.RealmVersionChecker$Companion",
    },
}
# Kotlin emits these implementation-only enum-switch mapping holders as public
# classes without ACC_SYNTHETIC.  The checked-in 10.19.0 inventory and javap
# oracle deliberately omit them, so keep that authoritative source-level API
# boundary with this exact, processor-only name set.
COMPILER_GENERATED_PUBLIC_CLASS_EXCLUSIONS = {
    "io.realm.processor.ClassMetaData$WhenMappings",
    "io.realm.processor.RealmProxyClassGenerator$WhenMappings",
    "io.realm.processor.Utils$WhenMappings",
}
RETIRED_PROCESSOR_BYTECODE_STRINGS = (b"RealmVersionChecker", b"static.realm.io")
PRODUCTION_SOURCE_APPROVALS = {
    "gradle-plugin/src/main/kotlin/io/realm/gradle/Realm.kt": "G004 public AGP migration",
    "library-build-transformer/src/main/kotlin/io/realm/buildtransformer/RealmBuildTransformer.kt": "G004 public AGP migration",
    "realm-transformer/src/main/kotlin/io/realm/transformer/RealmTransformer.kt": "G004-F001/F002",
    "realm-transformer/src/main/kotlin/io/realm/transformer/ext/ProjectExt.kt": "G004-F001",
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/RealmProcessor.kt": "retired checker removal",
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/RealmVersionChecker.kt": "retired checker removal",
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/CamelCaseConverter.kt": "F053",
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/LowerCaseWithSeparatorConverter.kt": "F053",
    "realm/realm-annotations-processor/src/main/java/io/realm/processor/nameconverter/PascalCaseConverter.kt": "F053",
}


class VerificationError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fail(message: str) -> None:
    raise VerificationError(message)


def is_unsupported(class_name: str) -> bool:
    return class_name.startswith(UNSUPPORTED_PREFIXES)


def artifact_file(root: Path, artifact: str, version: str, suffix: str) -> Path:
    path = root / artifact / version / f"{artifact}-{version}{suffix}"
    if not path.is_file():
        fail(f"missing {artifact} artifact: {path}")
    return path


def cache_artifact(cache: Path, artifact: str, suffix: str, expected_hash: str) -> Path:
    matches = sorted((cache / "io.realm" / artifact / OFFICIAL_VERSION).glob(f"*/{artifact}-{OFFICIAL_VERSION}{suffix}"))
    for match in matches:
        if sha256(match) == expected_hash:
            return match
    fail(f"official {artifact} cache artifact with expected SHA-256 is unavailable")


def load_official_hashes(root: Path) -> dict[str, str]:
    manifest = root / "evidence/oracle/official-10.19.0/maven-artifact-manifest.json"
    with manifest.open(encoding="utf-8") as source:
        coordinates = json.load(source)["coordinates"]
    return {item["artifactId"]: item["artifact_sha256_local"] for item in coordinates}


def oracle_evidence_hashes(root: Path) -> dict[str, str]:
    """Bind runtime comparisons to the checked-in public oracle inputs."""
    base = root / "evidence/oracle/official-10.19.0"
    paths = {
        "artifact_manifest": base / "maven-artifact-manifest.json",
        "public_class_inventory": base / "api/public-class-inventory.tsv",
        "public_api_javap": base / "api/public-api-javap.txt",
    }
    for name, path in paths.items():
        if not path.is_file():
            fail(f"missing official oracle input: {name}: {path}")
    return {name: sha256(path) for name, path in paths.items()}


def load_public_inventory(root: Path) -> dict[str, set[str]]:
    inventory = root / "evidence/oracle/official-10.19.0/api/public-class-inventory.tsv"
    classes = {artifact: set() for artifact in ARTIFACTS}
    with inventory.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source, delimiter="\t"):
            artifact = row["artifact"]
            if artifact not in classes:
                fail(f"unexpected artifact in public class inventory: {artifact}")
            flags = int(row["access_flags"], 16)
            if flags & 0x0001 and not flags & 0x1000:
                classes[artifact].add(row["class_name"])
    return classes


def normalize_javap_output(class_name: str, output: str) -> str:
    lines = []
    for line in output.splitlines():
        if line.startswith("Compiled from "):
            continue
        if not line.strip():
            continue
        # Kotlin's compiler-private bridge methods vary with the approved KGP
        # upgrade and do not represent a callable source-level public contract.
        if " access$" in line:
            continue
        if line in APPROVED_SIGNATURE_OMISSIONS.get(class_name, set()):
            continue
        approved_addition = APPROVED_COMPILER_SIGNATURE_ADDITIONS.get(class_name)
        if approved_addition and line == approved_addition["signature"]:
            continue
        # Methods exposing deliberately omitted Sync types are expected to go.
        if "io.realm.mongodb." in line or "getSubscriptions(" in line:
            continue
        lines.append(line.rstrip())
    if not lines:
        fail(f"javap emitted no declarations for {class_name}")
    # javap can reorder synthetic-adjacent constructors across JDK/Kotlin
    # versions; compare the declaration and member set, not that presentation.
    return "\n".join([lines[0], *sorted(lines[1:])]).strip()


def load_oracle_signatures(root: Path) -> dict[str, dict[str, str]]:
    api = (root / "evidence/oracle/official-10.19.0/api/public-api-javap.txt").read_text(encoding="utf-8")
    blocks = re.findall(
        r"^// artifact=([^ ]+) container=[^ ]+ class=([^\n]+)\n(.*?)(?=^// artifact=|\Z)",
        api,
        re.MULTILINE | re.DOTALL,
    )
    signatures = {artifact: {} for artifact in ARTIFACTS}
    for artifact, class_name, output in blocks:
        if artifact not in signatures:
            fail(f"unexpected artifact in public API oracle: {artifact}")
        # Keep the javap oracle aligned with class_entries and the checked-in
        # inventory: Kotlin's exact enum-switch holders are implementation
        # details even though javap prints them as public classes.
        if class_name in COMPILER_GENERATED_PUBLIC_CLASS_EXCLUSIONS:
            continue
        if class_name in signatures[artifact]:
            fail(f"duplicate public API oracle entry: {artifact}:{class_name}")
        signatures[artifact][class_name] = normalize_javap_output(class_name, output)
    return signatures


def class_access_flags(classfile: bytes) -> int:
    """Read the access flags after the JVM class-file constant pool."""
    if classfile[:4] != b"\xca\xfe\xba\xbe":
        fail("invalid class-file magic")
    offset = 10
    count = int.from_bytes(classfile[8:10], "big")
    index = 1
    while index < count:
        tag = classfile[offset]
        offset += 1
        if tag == 1:
            length = int.from_bytes(classfile[offset:offset + 2], "big")
            offset += 2 + length
        elif tag in {3, 4, 9, 10, 11, 12, 17, 18}:
            offset += 4
        elif tag in {5, 6}:
            offset += 8
            index += 1
        elif tag in {7, 8, 16, 19, 20}:
            offset += 2
        elif tag == 15:
            offset += 3
        else:
            fail(f"unsupported class-file constant-pool tag {tag}")
        index += 1
    return int.from_bytes(classfile[offset:offset + 2], "big")


def class_entries(archive: Path, extracted: Path) -> tuple[Path, dict[str, int]]:
    """Return a classpath JAR and checked public API class access flags."""
    extracted.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        if archive.suffix == ".aar":
            class_jar = extracted / f"{archive.stem}-classes.jar"
            class_jar.write_bytes(bundle.read("classes.jar"))
        else:
            class_jar = archive
    with zipfile.ZipFile(class_jar) as bundle:
        names = {}
        for name in bundle.namelist():
            if not name.endswith(".class") or name.startswith("META-INF/"):
                continue
            flags = class_access_flags(bundle.read(name))
            class_name = name.removesuffix(".class").replace("/", ".")
            # Kotlin compiler closures and lambdas are not source-level public
            # API. Compare only classes that are public and non-synthetic, plus
            # exclude the exact non-synthetic enum-switch holders omitted by
            # the checked-in official public API oracle.
            if (flags & 0x0001 and not flags & 0x1000
                    and class_name not in COMPILER_GENERATED_PUBLIC_CLASS_EXCLUSIONS):
                names[class_name] = flags
    return class_jar, names


@cache
def javap_signature(classpath: Path, class_name: str) -> str:
    result = subprocess.run(
        ["javap", "-public", "-classpath", str(classpath), class_name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        fail(f"javap failed for {class_name}: {result.stderr.strip()}")
    return normalize_javap_output(class_name, result.stdout)


def resource_entries(archive: Path) -> dict[str, str]:
    if archive.suffix != ".aar":
        return {}
    with zipfile.ZipFile(archive) as bundle:
        relevant = sorted(
            name for name in bundle.namelist()
            if name.startswith("res/") or name in {"R.txt", "public.txt"}
        )
        return {name: hashlib.sha256(bundle.read(name)).hexdigest() for name in relevant}


def cached_dependency(cache: Path, group: str, artifact: str, version: str) -> Path:
    matches = sorted((cache / group / artifact / version).glob(f"*/{artifact}-{version}.jar"))
    if not matches:
        fail(f"cached verifier dependency is unavailable: {group}:{artifact}:{version}")
    return matches[0]


def android_jar() -> Path:
    sdk = Path.home() / "Android/Sdk"
    candidates = sorted((sdk / "platforms").glob("android-37*/android.jar"))
    if not candidates:
        fail("Android API 37 platform jar is unavailable for generated-output verification")
    return candidates[-1]


def processor_output(
    cache: Path,
    processor: Path,
    annotations: Path,
    library: Path,
    kotlin_version: str,
    output: Path,
) -> dict[str, str]:
    """Generate a minimal model's proxy/module output with a released processor."""
    classes, _ = class_entries(library, output / "library")
    source = output / "src/fixture/Sample.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "package fixture;\n"
        "import io.realm.RealmObject;\n"
        "public class Sample extends RealmObject { public String name; }\n",
        encoding="utf-8",
    )
    generated = output / "generated"
    classpath = [
        processor,
        annotations,
        classes,
        android_jar(),
        cached_dependency(cache, "org.jetbrains.kotlin", "kotlin-stdlib", kotlin_version),
        cached_dependency(cache, "org.jetbrains.kotlin", "kotlin-stdlib-jdk8", kotlin_version),
        cached_dependency(cache, "com.squareup", "javawriter", "2.5.1"),
        cached_dependency(cache, "org.mongodb", "bson", "3.12.1"),
    ]
    command = [
        "javac", "-proc:only", "-cp", ":".join(map(str, classpath)),
        "-processorpath", ":".join(map(str, classpath)), "-processor", "io.realm.processor.RealmProcessor",
        "-s", str(generated), str(source),
    ]
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        fail(f"generated accessor/module/proxy fixture failed:\n{result.stdout}")
    return {
        path.relative_to(generated).as_posix(): sha256(path)
        for path in sorted(generated.rglob("*.java"))
    }


def compare_generated_outputs(
    cache: Path, official: dict[str, Path], local: dict[str, Path], temporary: Path
) -> dict[str, str]:
    official_outputs = processor_output(
        cache, official["realm-annotations-processor"], official["realm-annotations"],
        official["realm-android-library"], "1.6.21", temporary / "official",
    )
    local_outputs = processor_output(
        cache, local["realm-annotations-processor"], local["realm-annotations"],
        local["realm-android-library"], "2.2.10", temporary / "fork",
    )
    if official_outputs != local_outputs:
        missing = sorted(set(official_outputs) - set(local_outputs))
        added = sorted(set(local_outputs) - set(official_outputs))
        changed = sorted(name for name in official_outputs.keys() & local_outputs.keys()
                         if official_outputs[name] != local_outputs[name])
        fail(f"generated accessor/module/proxy delta: missing={missing}, added={added}, changed={changed}")
    return official_outputs


def verify_staging_hashes(local: dict[str, Path]) -> None:
    for artifact in local.values():
        sidecar = artifact.with_name(f"{artifact.name}.sha256")
        if not sidecar.is_file() or sidecar.read_text(encoding="utf-8").strip() != sha256(artifact):
            fail(f"staging SHA-256 sidecar mismatch: {artifact.name}")
        pom = artifact.with_suffix(".pom")
        if pom.is_file() and re.search(r"jitpack|sync|objectserver", pom.read_text(encoding="utf-8"), re.I):
            fail(f"unsupported repository/runtime reference in staged POM: {pom.name}")


def verify_retired_processor_absence(processor: Path) -> dict[str, object]:
    """Assert the expressly retired network checker is absent from published bytes."""
    matches: dict[str, list[str]] = {}
    with zipfile.ZipFile(processor) as archive:
        for info in archive.infolist():
            payload = archive.read(info)
            forbidden = [needle.decode("ascii") for needle in RETIRED_PROCESSOR_BYTECODE_STRINGS if needle in payload]
            if forbidden:
                matches[info.filename] = forbidden
    if matches:
        fail(f"retired processor checker/endpoint remains in bytecode: {matches}")
    return {
        "approved_removed_public_classes": sorted(
            APPROVED_PUBLIC_CLASS_REMOVALS["realm-annotations-processor"]
        ),
        "absent_bytecode_strings": [needle.decode("ascii") for needle in RETIRED_PROCESSOR_BYTECODE_STRINGS],
    }


def g006_stable_api_decision_path(root: Path) -> Path:
    """Find the leader-owned accepted G006 decision from a team worktree."""
    for candidate_root in (root, *root.parents):
        candidate = candidate_root / G006_STABLE_API_DECISION
        if candidate.is_file():
            return candidate
    fail(f"accepted G006 stable-API decision is unavailable: {G006_STABLE_API_DECISION}")


def verify_compiler_signature_addition(root: Path, processor: Path, temporary: Path) -> dict[str, object]:
    """Pin the sole KGP 2.2 enum ABI addition to one class and descriptor."""
    source = "realm/realm-annotations-processor/src/main/java/io/realm/processor/Constants.kt"
    unchanged = subprocess.run(
        ["git", "diff", "--quiet", f"{BASELINE_TAG}...HEAD", "--", source], cwd=root, check=False
    ).returncode == 0
    if not unchanged:
        fail(f"compiler-signature exception source changed from {BASELINE_TAG}: {source}")
    dependencies = (root / "dependencies.list").read_text(encoding="utf-8")
    if not re.search(r"^KOTLIN=2\.2\.10$", dependencies, re.MULTILINE):
        fail("approved compiler-signature exception requires KOTLIN=2.2.10")
    g006_decision = g006_stable_api_decision_path(root)

    classpath, _ = class_entries(processor, temporary / "processor")
    for class_name, expected in APPROVED_COMPILER_SIGNATURE_ADDITIONS.items():
        output = subprocess.run(
            ["javap", "-public", "-s", "-classpath", str(classpath), class_name],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if output.returncode:
            fail(f"javap descriptor check failed for {class_name}: {output.stderr.strip()}")
        pattern = re.escape(expected["signature"]) + r"\n\s*descriptor: " + re.escape(expected["descriptor"])
        if not re.search(pattern, output.stdout):
            fail(f"approved compiler signature is missing or has the wrong descriptor: {class_name}")
    return {
        "approval": "leader Task8 decision: KGP 2.2.10 compiler-generated additive enum ABI only",
        "source_unchanged_from": BASELINE_TAG,
        "required_kotlin_version": "2.2.10",
        "exact_allowlist": APPROVED_COMPILER_SIGNATURE_ADDITIONS,
        "prior_g006_stable_api_decision_path": G006_STABLE_API_DECISION,
        "prior_g006_stable_api_decision_sha256": sha256(g006_decision),
    }


def verify_official_oracle(
    root: Path, official: dict[str, Path], temporary: Path
) -> dict[str, object]:
    """Confirm the downloaded, manifest-pinned JARs are the checked-in oracle."""
    inventory = load_public_inventory(root)
    signatures = load_oracle_signatures(root)
    counts = {}
    for artifact, archive in official.items():
        classpath, classes = class_entries(archive, temporary / artifact)
        actual = set(classes)
        if actual != inventory[artifact]:
            missing = sorted(inventory[artifact] - actual)
            added = sorted(actual - inventory[artifact])
            fail(f"official {artifact} public inventory mismatch: missing={missing}, added={added}")
        if set(signatures[artifact]) != actual:
            missing = sorted(actual - set(signatures[artifact]))
            added = sorted(set(signatures[artifact]) - actual)
            fail(f"official {artifact} public API oracle mismatch: missing={missing}, added={added}")
        for class_name in sorted(actual):
            if javap_signature(classpath, class_name) != signatures[artifact][class_name]:
                fail(f"official {artifact} public API signature mismatch: {class_name}")
        counts[artifact] = len(actual)
    return {"verified_public_class_counts": counts}


def compare_artifact(name: str, official: Path, local: Path, temporary: Path) -> dict[str, object]:
    official_jar, official_classes = class_entries(official, temporary / "official")
    local_jar, local_classes = class_entries(local, temporary / "local")
    official_supported = {item for item in official_classes if not is_unsupported(item)}
    local_supported = {item for item in local_classes if not is_unsupported(item)}
    approved_removals = APPROVED_PUBLIC_CLASS_REMOVALS.get(name, set())
    if approved_removals - official_supported:
        fail(f"{name} approved public removal is absent from the official baseline")
    present_retired = sorted(approved_removals & local_supported)
    if present_retired:
        fail(f"{name} retired public class remains published: {present_retired}")
    missing = sorted(official_supported - local_supported - approved_removals)
    added = sorted(local_supported - official_supported)
    if missing or added:
        fail(f"{name} public-class delta: missing={missing}, added={added}")

    signature_deltas = []
    for class_name in sorted(official_supported - approved_removals):
        if javap_signature(official_jar, class_name) != javap_signature(local_jar, class_name):
            signature_deltas.append(class_name)
    if signature_deltas:
        fail(f"{name} public-signature delta: {signature_deltas}")

    official_resources = resource_entries(official)
    local_resources = resource_entries(local)
    if official_resources != local_resources:
        fail(f"{name} Android resource delta")
    return {
        "official_sha256": sha256(official),
        "fork_sha256": sha256(local),
        "public_class_count": len(official_supported),
        "approved_removed_public_classes": sorted(approved_removals),
        "resource_entry_count": len(official_resources),
    }


def verify_scope(root: Path) -> dict[str, object]:
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", f"{BASELINE_TAG}...HEAD"], cwd=root, text=True
    ).splitlines()
    source_changes = [
        path for path in changed
        if re.search(r"/src/main/.*\.(?:java|kt|c|cpp|h)$", path)
        and path.startswith(("gradle-plugin/", "library-build-transformer/", "realm-transformer/", "realm/"))
        and not path.startswith(GENERATED_JNI_PREFIX)
        and path != "realm/realm-library/src/main/cpp/realm-core"
    ]
    unapproved = [path for path in source_changes if path not in PRODUCTION_SOURCE_APPROVALS]
    if unapproved:
        fail(f"unapproved production source delta(s): {unapproved}")

    generated_headers = [path for path in changed if path.startswith(GENERATED_JNI_PREFIX)]
    if generated_headers:
        manifest = root / GENERATED_JNI_PREFIX / "SHA256SUMS"
        if not manifest.is_file():
            fail("generated JNI headers changed without SHA256SUMS")
        result = subprocess.run(["sha256sum", "--check", manifest.name], cwd=manifest.parent, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        if result.returncode:
            fail(f"generated JNI header manifest failed: {result.stdout.strip()}")

    graph = subprocess.run(
        ["./gradlew", "--no-daemon", "--offline", "--console=plain", "--dry-run", "installRealmJava"],
        cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if graph.returncode:
        fail(f"supported G009 graph dry-run failed:\n{graph.stdout}")
    forbidden = [line for line in graph.stdout.splitlines() if re.search(r"sync|objectserver|network", line, re.I)]
    if forbidden:
        fail(f"supported G009 graph contains forbidden work: {forbidden}")
    return {
        "approved_production_source_changes": {
            path: PRODUCTION_SOURCE_APPROVALS[path] for path in sorted(source_changes)
        },
        "generated_jni_header_changes": len(generated_headers),
        "supported_graph": [line for line in graph.stdout.splitlines() if line.startswith(":")],
    }


def write_report_and_checksums(output: Path, filename: str, report: dict[str, object]) -> Path:
    report_path = output / filename
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksums = []
    for name, artifact in sorted(report.get("artifact_hashes", {}).items()):
        checksums.append(f"{artifact['official_sha256']}  official/{name}")
        checksums.append(f"{artifact['fork_sha256']}  fork/{name}")
    checksums.append(f"{sha256(report_path)}  {filename}")
    (output / "checksums.sha256").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--official-cache", type=Path, default=Path.home() / ".gradle/caches/modules-2/files-2.1")
    parser.add_argument(
        "--fork-repository",
        type=Path,
        default=Path("/mnt/d/workspace/jiran/realm/build/g008-root-final-stage-run1/io/github/leminity/realm"),
        help="G008 staging repository; never resolve a remote/JitPack substitute",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output_dir or root / "evidence/g009/ac09").resolve()
    output.mkdir(parents=True, exist_ok=True)
    official_hashes = load_official_hashes(root)

    report: dict[str, object] = {
        "baseline": {"version": OFFICIAL_VERSION, "tag": BASELINE_TAG},
        "fork_version": FORK_VERSION,
        "official_oracle_sha256": oracle_evidence_hashes(root),
        "artifact_hashes": {},
        "artifacts": {},
    }
    try:
        with tempfile.TemporaryDirectory(prefix="g009-ac09-") as temporary:
            temp = Path(temporary)
            official_artifacts = {}
            local_artifacts = {}
            for name, suffix in ARTIFACTS.items():
                official = cache_artifact(args.official_cache, name, suffix, official_hashes[name])
                local = artifact_file(args.fork_repository, name, FORK_VERSION, suffix)
                official_artifacts[name] = official
                local_artifacts[name] = local
                report["artifact_hashes"][name] = {
                    "official_sha256": sha256(official),
                    "fork_sha256": sha256(local),
                }
            for name in ARTIFACTS:
                official = official_artifacts[name]
                local = local_artifacts[name]
                report["artifacts"][name] = compare_artifact(name, official, local, temp / name)
            verify_staging_hashes(local_artifacts)
            report["official_oracle_validation"] = verify_official_oracle(
                root, official_artifacts, temp / "official-oracle"
            )
            report["retired_processor_checker_absence"] = verify_retired_processor_absence(
                local_artifacts["realm-annotations-processor"]
            )
            report["approved_compiler_signature_addition"] = verify_compiler_signature_addition(
                root, local_artifacts["realm-annotations-processor"], temp / "compiler-signature"
            )
            report["generated_accessor_module_proxy_outputs"] = compare_generated_outputs(
                args.official_cache, official_artifacts, local_artifacts, temp / "generated-output"
            )
        report["scope_audit"] = verify_scope(root)
    except VerificationError as error:
        report["status"] = "FAIL"
        report["failure"] = str(error)
        write_report_and_checksums(output, "failure-report.json", report)
        print(f"AC-09 compatibility verification: FAIL: {error}", file=sys.stderr)
        return 1

    report["status"] = "PASS"
    write_report_and_checksums(output, "report.json", report)
    print("AC-09 compatibility verification: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
