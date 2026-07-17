#!/usr/bin/env python3
"""Regression tests for the deterministic G011 source/evidence manifest."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("g011-evidence-manifest.py")
SPEC = importlib.util.spec_from_file_location("g011_evidence_manifest", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ManifestTests(unittest.TestCase):
    def test_build_manifest_structure_and_pins(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = MODULE.build_manifest(root)

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["source"]["baseline_root_commit"], MODULE.EXPECTED_ROOT_COMMIT)
        self.assertEqual(manifest["source"]["current_head_commit"], MODULE.EXPECTED_CURRENT_HEAD_COMMIT)
        self.assertEqual(manifest["source"]["core_commit"], MODULE.EXPECTED_CORE_COMMIT)
        self.assertEqual(manifest["toolchain"]["gradle_version"], MODULE.EXPECTED_GRADLE)
        self.assertEqual(manifest["toolchain"]["agp_version"], MODULE.EXPECTED_AGP)
        self.assertEqual(manifest["toolchain"]["min_sdk"], MODULE.EXPECTED_MIN_SDK)
        self.assertEqual(manifest["toolchain"]["compile_sdk"], MODULE.EXPECTED_COMPILE_SDK)
        self.assertEqual(manifest["toolchain"]["target_sdk"], MODULE.EXPECTED_TARGET_SDK)
        self.assertEqual(manifest["toolchain"]["release_graph"]["supported_abis"], sorted(MODULE.EXPECTED_ABIS))
        self.assertTrue(manifest["toolchain"]["release_graph"]["no_x86"])
        self.assertEqual(manifest["toolchain"]["release_graph"]["minimum_elf_alignment"], MODULE.EXPECTED_ELF_MIN_ALIGNMENT)
        self.assertEqual(manifest["wsl"]["page_size"], MODULE.EXPECTED_DEVICE_PAGE_SIZE)
        self.assertEqual(manifest["wsl"]["model"], MODULE.EXPECTED_DEVICE_MODEL)
        self.assertIn(".github/workflows/ci.yml", manifest["gate_digests"])
        self.assertIn(".github/workflows/release.yml", manifest["gate_digests"])
        self.assertIn("tools/central-portal.py", manifest["gate_digests"])
        self.assertIn("tools/test-central-portal.py", manifest["gate_digests"])
        self.assertIn("compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh", manifest["gate_digests"])
        self.assertIn("tools/verify-g003-independent-builds.sh", manifest["gate_digests"])
        self.assertIn("tools/verify-g010-scope.py", manifest["gate_digests"])
        self.assertIn("evidence/toolchain/android17-wsl2/environment-diagnostics.txt", manifest["evidence"]["toolchain_android17_wsl2"]["files"])

    def test_canonical_json_is_stable(self) -> None:
        payload = {"b": 2, "a": 1}
        self.assertEqual(MODULE.canonical_json(payload), '{\n  "a": 1,\n  "b": 2\n}\n')

    def test_tree_digest_ignores_generated_build_products(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence/toolchain/android17-wsl2"
            evidence.mkdir(parents=True)
            (evidence / "keep.txt").write_text("keep", encoding="utf-8")

            before = MODULE.tree_digest(root, Path("evidence/toolchain/android17-wsl2"))

            for relative in (
                "evidence/toolchain/android17-wsl2/build/generated.bin",
                "evidence/toolchain/android17-wsl2/.gradle/cache.bin",
                "evidence/toolchain/android17-wsl2/downloads/archive.zip",
                "evidence/toolchain/android17-wsl2/extraction/unpacked.txt",
                "evidence/toolchain/android17-wsl2/SHA256SUMS",
                "evidence/toolchain/android17-wsl2/checksum-verify.log",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ignored", encoding="utf-8")

            after = MODULE.tree_digest(root, Path("evidence/toolchain/android17-wsl2"))

            self.assertEqual(before["file_count"], 1)
            self.assertEqual(before["tree_sha256"], after["tree_sha256"])
            self.assertEqual(after["file_count"], 1)
            self.assertEqual(sorted(after["files"].keys()), ["evidence/toolchain/android17-wsl2/keep.txt"])

    def test_verify_mode_rejects_changed_manifest(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "manifest.json"
            output.write_text(MODULE.canonical_json({"schema_version": 0}), encoding="utf-8")
            self.assertNotEqual(MODULE.canonical_json(MODULE.build_manifest(root)), output.read_text(encoding="utf-8"))

    def test_ci_workflow_is_pinned_and_runs_the_required_gates(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("contents: read", workflow)
        self.assertIn("runs-on: [self-hosted, linux, api37, ps16k]", workflow)
        self.assertIn("actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683", workflow)
        self.assertIn("actions/setup-java@03ad4de0992f5dab5e18fcb136590ce7c4a0ac95", workflow)
        self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("workflow_dispatch", workflow)
        self.assertIn("tools/verify-toolchain.sh", workflow)
        self.assertIn("tools/test-g011-evidence-manifest.py", workflow)
        self.assertIn("tools/verify-g003-independent-builds.sh --run --evidence-dir build/g003-independent-builds", workflow)
        self.assertIn("runtime_sha_tmp", workflow)
        self.assertIn('mv "$runtime_sha_tmp" "$runtime_sha"', workflow)
        self.assertIn("tools/test-g008-publication.py", workflow)
        self.assertIn("tools/test-verify-g009-ac09-compatibility.py", workflow)
        self.assertIn("tools/test-verify-g010-scope.py", workflow)
        self.assertIn("tools/test-verify-g010-license.py", workflow)
        self.assertIn("tools/test-central-portal.py", workflow)
        self.assertIn("compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh", workflow)
        self.assertIn("retention-days: 14", workflow)


if __name__ == "__main__":
    unittest.main()
