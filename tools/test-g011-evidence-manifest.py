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
        self.assertEqual(manifest["source"]["core_commit"], MODULE.EXPECTED_CORE_COMMIT)
        self.assertEqual(manifest["toolchain"]["gradle_version"], MODULE.EXPECTED_GRADLE)
        self.assertEqual(manifest["toolchain"]["agp_version"], MODULE.EXPECTED_AGP)
        self.assertEqual(manifest["toolchain"]["min_sdk"], MODULE.EXPECTED_MIN_SDK)
        self.assertEqual(manifest["toolchain"]["compile_sdk"], MODULE.EXPECTED_COMPILE_SDK)
        self.assertEqual(manifest["toolchain"]["target_sdk"], MODULE.EXPECTED_TARGET_SDK)
        self.assertEqual(manifest["toolchain"]["release_graph"]["supported_abis"], sorted(MODULE.EXPECTED_ABIS))
        self.assertTrue(manifest["toolchain"]["release_graph"]["no_x86"])
        self.assertEqual(manifest["wsl"]["page_size"], MODULE.EXPECTED_DEVICE_PAGE_SIZE)
        self.assertEqual(manifest["wsl"]["model"], MODULE.EXPECTED_DEVICE_MODEL)
        self.assertIn("tools/verify-g010-scope.py", manifest["gate_digests"])
        self.assertIn("evidence/toolchain/android17-wsl2/environment-diagnostics.txt", manifest["evidence"]["toolchain_android17_wsl2"]["files"])

    def test_canonical_json_is_stable(self) -> None:
        payload = {"b": 2, "a": 1}
        self.assertEqual(MODULE.canonical_json(payload), '{\n  "a": 1,\n  "b": 2\n}\n')

    def test_verify_mode_rejects_changed_manifest(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "manifest.json"
            output.write_text(MODULE.canonical_json({"schema_version": 0}), encoding="utf-8")
            self.assertNotEqual(MODULE.canonical_json(MODULE.build_manifest(root)), output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
