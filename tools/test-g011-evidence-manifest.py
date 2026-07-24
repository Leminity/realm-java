#!/usr/bin/env python3
# Modified by Leminity from the upstream Realm Java project.
"""Regression tests for the deterministic G011 provenance contract."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("g011-evidence-manifest.py")
SPEC = importlib.util.spec_from_file_location("g011_evidence_manifest", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_runtime_evidence(root: Path) -> None:
    paths = list(MODULE.RUNTIME_REQUIRED_EXACT) + [f"{prefix}fixture.txt" for prefix in MODULE.RUNTIME_REQUIRED_PREFIXES]
    for relative in paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((relative + "\n").encode())
    entries = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        entries.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{relative}\n")
    (root / "SHA256SUMS").write_text("".join(entries), encoding="utf-8")
    (root / "checksum-verify.log").write_text("all files: OK\n", encoding="utf-8")


class ManifestTests(unittest.TestCase):
    def test_core_provenance_uses_gitlink_object_store(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            MODULE.EXPECTED_CORE_COMMIT,
            MODULE.run_core_git(root, "rev-parse", f"{MODULE.EXPECTED_CORE_COMMIT}^{{commit}}"),
        )
        self.assertEqual(
            set(MODULE.EXPECTED_CORE_SUBMODULE_PATHS),
            set(MODULE.exact_core_submodules(root)),
        )

    def test_baseline_structure_and_pins(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = MODULE.build_manifest(root, "baseline")
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["manifest_kind"], "baseline")
        self.assertEqual(manifest["source"]["baseline_root_commit"], MODULE.EXPECTED_BASELINE_COMMIT)
        self.assertNotIn("current_head_commit", manifest["source"])
        self.assertNotIn("ci", manifest)
        self.assertEqual(manifest["source"]["core_commit"], MODULE.EXPECTED_CORE_COMMIT)
        self.assertEqual(set(manifest["source"]["core_submodules"]), set(MODULE.EXPECTED_CORE_SUBMODULE_PATHS))
        self.assertEqual(manifest["toolchain"]["gradle_version"], "9.6.1")
        self.assertEqual(manifest["toolchain"]["agp_version"], "9.1.1")
        self.assertEqual(manifest["toolchain"]["min_sdk"], 21)
        self.assertEqual(manifest["toolchain"]["compile_sdk"], 37)
        self.assertEqual(manifest["toolchain"]["target_sdk"], 37)
        self.assertEqual(manifest["toolchain"]["release_graph"]["supported_abis"], sorted(MODULE.EXPECTED_ABIS))
        self.assertTrue(manifest["toolchain"]["release_graph"]["no_x86"])
        self.assertEqual(manifest["wsl"]["page_size"], 16384)
        self.assertEqual(manifest["wsl"]["model"], MODULE.EXPECTED_DEVICE_MODEL)
        for required in MODULE.GATE_PATHS:
            self.assertIn(required, manifest["gate_digests"])

    def test_runtime_binds_exact_dynamic_head_and_checksums(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "evidence"
            evidence.mkdir()
            write_runtime_evidence(evidence)
            manifest = MODULE.build_manifest(root, "runtime", evidence)
            head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            self.assertEqual(manifest["manifest_kind"], "runtime")
            self.assertEqual(manifest["source"]["current_head_commit"], head)
            self.assertTrue(manifest["ci"]["checksum_verified"])
            self.assertEqual(
                manifest["ci"]["file_count"],
                len(MODULE.RUNTIME_REQUIRED_EXACT) + len(MODULE.RUNTIME_REQUIRED_PREFIXES),
            )
            self.assertNotIn(str(evidence.parent), MODULE.canonical_json(manifest))

    def test_runtime_rejects_missing_stale_and_modified_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary)
            write_runtime_evidence(evidence)
            (evidence / "g003/gate.log").unlink()
            with self.assertRaisesRegex(MODULE.ManifestError, "checksum coverage differs"):
                MODULE.runtime_evidence_digest(evidence)
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary)
            write_runtime_evidence(evidence)
            (evidence / "g003/gate.log").write_text("mutated", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ManifestError, "checksum mismatch"):
                MODULE.runtime_evidence_digest(evidence)
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary)
            write_runtime_evidence(evidence)
            (evidence / "unexpected.txt").write_text("stale", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ManifestError, "checksum coverage differs"):
                MODULE.runtime_evidence_digest(evidence)

    def test_tracked_tree_ignores_untracked_products_and_rejects_missing_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = Path("evidence/toolchain/android17-wsl2")
            tracked = root / relative / "keep.txt"
            tracked.parent.mkdir(parents=True)
            tracked.write_text("keep", encoding="utf-8")
            original = MODULE.tracked_files
            MODULE.tracked_files = lambda _root, _relative: ((relative / "keep.txt").as_posix(),)
            try:
                before = MODULE.tree_digest(root, relative)
                for name in ("build/generated.bin", ".gradle/cache.bin", "downloads/archive.zip", "SHA256SUMS"):
                    path = root / relative / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("volatile", encoding="utf-8")
                after = MODULE.tree_digest(root, relative)
                self.assertEqual(before, after)
                tracked.unlink()
                with self.assertRaisesRegex(MODULE.ManifestError, "missing tracked evidence"):
                    MODULE.tree_digest(root, relative)
            finally:
                MODULE.tracked_files = original

    def test_runtime_mode_requires_fresh_evidence_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with self.assertRaisesRegex(MODULE.ManifestError, "requires --runtime-evidence-dir"):
            MODULE.build_manifest(root, "runtime")
        self.assertFalse(hasattr(MODULE, "EXPECTED_CURRENT_HEAD_COMMIT"))

    def test_runtime_rejects_tracked_or_staged_source_changes(self) -> None:
        original = MODULE.run_git
        MODULE.run_git = lambda _root, *args: " M tracked.file" if args[0] == "status" else original(_root, *args)
        try:
            with self.assertRaisesRegex(MODULE.ManifestError, "cannot bind exact HEAD"):
                MODULE.assert_runtime_source_clean(Path.cwd())
        finally:
            MODULE.run_git = original

    def test_cli_baseline_and_runtime_round_trip(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            baseline = temp / "baseline.json"
            subprocess.run([str(SCRIPT), "--mode", "baseline", "--output", str(baseline)], cwd=root, check=True)
            subprocess.run([str(SCRIPT), "--mode", "baseline", "--verify", str(baseline)], cwd=root, check=True)
            evidence = temp / "evidence"
            evidence.mkdir()
            write_runtime_evidence(evidence)
            runtime = temp / "runtime.json"
            command = [str(SCRIPT), "--mode", "runtime", "--runtime-evidence-dir", str(evidence)]
            subprocess.run([*command, "--output", str(runtime)], cwd=root, check=True)
            subprocess.run([*command, "--verify", str(runtime)], cwd=root, check=True)

    def test_ci_workflow_is_pinned_ordered_and_executable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        native_verifier = (root / "tools/g011-verify-native-elf.sh").read_text(encoding="utf-8")
        directly_executed_shell_scripts = (
            "tools/verify-toolchain.sh",
            "tools/publish_release.sh",
            "tools/g011-consume-six.sh",
            "tools/g011-verify-native-elf.sh",
            "compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh",
            "compatibility-fixtures/ac07-bidirectional/run-ac07.sh",
        )
        for relative in directly_executed_shell_scripts:
            index_entry = MODULE.run_git(root, "ls-files", "--stage", "--", relative)
            with self.subTest(relative=relative):
                self.assertEqual(index_entry.split(maxsplit=1)[0], "100755")
        self.assertIn('report="$evidence/report.txt"', native_verifier)
        self.assertIn("native/report.txt", MODULE.RUNTIME_REQUIRED_EXACT)
        self.assertNotIn("native/result.txt", MODULE.RUNTIME_REQUIRED_EXACT)
        self.assertIn("portal/g013-direct-validation-workflow-unit.log", MODULE.RUNTIME_REQUIRED_EXACT)
        self.assertIn("portal/g014-release-binding-unit.log", MODULE.RUNTIME_REQUIRED_EXACT)
        self.assertIn("tools/test-g013-direct-validation-workflow.py", MODULE.GATE_PATHS)
        self.assertIn("tools/test-g014-release-binding.py", MODULE.GATE_PATHS)
        for required_gate in (
            "compatibility-fixtures/ac07-bidirectional/run-ac07.sh",
            "compatibility-fixtures/ac07-bidirectional/verify-ac07-results.py",
        ):
            self.assertIn(required_gate, MODULE.GATE_PATHS)
        for required_evidence in (
            "ac07/RESULT.txt",
            "ac07/fork-modified/fork-report.json",
            "ac07/logs/fork-instrumentation.log",
            "ac07/logs/official-reverse-instrumentation.log",
            "ac07/original/immutable-input.sha256",
            "ac07/original/immutable-input-after.sha256",
            "ac07/logs/immutable-input-diff.log",
        ):
            self.assertIn(required_evidence, MODULE.RUNTIME_REQUIRED_EXACT)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("runs-on: [self-hosted, linux, api37, ps16k]", workflow)
        self.assertIn("actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683", workflow)
        self.assertIn("actions/setup-java@03ad4de0992f5dab5e18fcb136590ce7c4a0ac95", workflow)
        self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", workflow)
        self.assertIn("include-hidden-files: true", workflow)
        for forbidden in ("pull_request_target", "workflow_dispatch", "ubuntu-latest", "build/g008-root-final-stage-run1"):
            self.assertNotIn(forbidden, workflow)
        required = (
            "tools/verify-toolchain.sh",
            "tools/verify-g003-independent-builds.sh",
            "tools/verify-g004-transformer-public-api.sh",
            "./gradle-plugin/gradlew --project-dir gradle-plugin --no-daemon --console=plain",
            "tools/publish_release.sh",
            "tools/g011-consume-six.sh",
            "tools/g011-verify-native-elf.sh",
            "compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh",
            "tools/verify-g009-ac09-compatibility.py",
            "tools/verify-g010-scope.py",
            "tools/verify-g010-license.py",
            "tools/test-central-portal.py",
            "tools/test-g013-direct-validation-workflow.py",
            "tools/test-g014-release-binding.py",
            "--mode runtime",
            "--runtime-evidence-dir \"$G011_EVIDENCE_ROOT\"",
            "sha256sum -c SHA256SUMS",
            "retention-days: 14",
        )
        for text in required:
            self.assertIn(text, workflow)
        self.assertNotIn("./gradle-plugin/gradlew --no-daemon --console=plain cleanTest test", workflow)
        g003_step = workflow[
            workflow.index("tools/verify-g003-independent-builds.sh") : workflow.index("G004 public AGP transformer TestKit gate")
        ]
        g004_step = workflow[
            workflow.index("tools/verify-g004-transformer-public-api.sh") : workflow.index("G005 realm-android plugin TestKit gate")
        ]
        g005_step = workflow[
            workflow.index("G005 realm-android plugin TestKit gate") : workflow.index("Fresh G008 signed six-artifact bundle")
        ]
        publication_step = workflow[
            workflow.index("tools/publish_release.sh") : workflow.index("G011 exact-six fresh consumer gate")
        ]
        self.assertIn("--run", g003_step)
        self.assertIn("--run", g004_step)
        self.assertIn('g005_maven_repository="$(mktemp -d "$RUNNER_TEMP/g005-maven-repository.XXXXXX")"', g005_step)
        self.assertEqual(g005_step.count('"-Dmaven.repo.local=$g005_maven_repository"'), 2)
        self.assertEqual(g005_step.count('"-Pg008StagingRepository=$g005_maven_repository"'), 2)
        self.assertLess(g005_step.index("g008PublishTransformer"), g005_step.index("./gradle-plugin/gradlew"))
        self.assertNotIn("$HOME/.m2", g005_step)
        self.assertIn("--signed-bundle", publication_step)
        self.assertIn("g008SigningKey", workflow)
        self.assertIn("--export-secret-keys", workflow)
        self.assertNotIn("evidence/oracle/official-10.19.0/artifacts", workflow)
        self.assertIn("io.realm:realm-gradle-plugin:10.19.0", workflow)
        self.assertIn("io.realm:realm-android-library:10.19.0@aar", workflow)
        self.assertIn("org.jetbrains.kotlin:kotlin-stdlib:1.6.21", workflow)
        self.assertIn("org.jetbrains.kotlin:kotlin-stdlib:2.2.10", workflow)
        self.assertIn("com.squareup:javawriter:2.5.1", workflow)
        self.assertIn("org.mongodb:bson:3.12.1", workflow)
        self.assertIn("g009OfficialProcessor", workflow)
        self.assertIn("g009ForkProcessor", workflow)
        self.assertIn('--official-cache "$official_home/caches/modules-2/files-2.1"', workflow)
        g009_step = workflow[
            workflow.index("G009 public API and resource gate") : workflow.index("G010 scope gate")
        ]
        self.assertNotIn("mavenLocal", g009_step)
        self.assertNotIn("jitpack", g009_step.lower())
        self.assertIn('--mode local \\\n            --repository "$G008_STAGING"', workflow)
        self.assertNotIn("--mode local \\\n            --repository-url", workflow)
        ac07_command = """compatibility-fixtures/ac07-bidirectional/run-ac07.sh \\
            --official-fixtures compatibility-fixtures/official-10.19.0-generator/generated/official-10.19.0-oracle \\
            --fork-repository "$G008_STAGING" \\
            --fork-serial emulator-5654 \\
            --official-serial emulator-5654 \\
            --run-dir "$G011_EVIDENCE_ROOT/ac07"""
        self.assertEqual(workflow.count(ac07_command), 1)
        self.assertEqual(workflow.count("compatibility-fixtures/ac07-bidirectional/run-ac07.sh"), 1)
        release_workflow = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertNotIn("compatibility-fixtures/ac07-bidirectional/run-ac07.sh", release_workflow)
        ac07_index = workflow.index(ac07_command)
        self.assertGreater(ac07_index, workflow.index("tools/g011-verify-native-elf.sh"))
        self.assertGreater(ac07_index, workflow.index("tools/publish_release.sh"))
        self.assertLess(ac07_index, workflow.index("Seal complete evidence and create exact runtime manifest"))
        runtime_index = workflow.index("--mode runtime")
        self.assertGreater(runtime_index, workflow.index("G011 AC08 local gate"))
        self.assertGreater(runtime_index, workflow.index("G010 publication and license gate"))
        self.assertGreater(runtime_index, workflow.index("Portal and protected-release unit gate"))
        self.assertGreater(workflow.index("Upload complete G011 evidence"), runtime_index)
        upload_step = workflow[workflow.index("Upload complete G011 evidence") :]
        for required_path in (
            "${{ env.G011_EVIDENCE_ROOT }}",
            "${{ env.G011_RUNTIME_MANIFEST }}",
            "${{ env.G011_RUNTIME_SHA }}",
            "if-no-files-found: error",
        ):
            self.assertIn(required_path, upload_step)
        self.assertIn('tee "$G011_EVIDENCE_ROOT/g008/unit.log"', workflow)
        self.assertIn('tee "$G011_EVIDENCE_ROOT/provenance/manifest-unit.log"', workflow)
        self.assertEqual(workflow.count("G011 AC08 local gate"), 1)


if __name__ == "__main__":
    unittest.main()
