#!/usr/bin/env python3
"""Regression tests for the G002 RealmModule constructor verifier."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "tools" / "verify-g002-realmmodule-constructor-rule.sh"
RULES = ROOT / "realm" / "realm-library" / "proguard-rules-consumer-common.pro"
EXPECTED_RULE = """-keep @io.realm.annotations.RealmModule class * {
    <init>(...);
}"""


class RealmModuleConstructorVerifierTest(unittest.TestCase):
    def run_verifier(
        self, root_override: pathlib.Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        if root_override is not None:
            environment["ROOT_OVERRIDE"] = str(root_override)
        return subprocess.run(
            [str(VERIFIER)],
            check=False,
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
        )

    def copy_rules(self, directory: pathlib.Path) -> pathlib.Path:
        copied = (
            directory
            / "realm"
            / "realm-library"
            / "proguard-rules-consumer-common.pro"
        )
        copied.parent.mkdir(parents=True)
        shutil.copy2(RULES, copied)
        return copied

    def test_current_source_and_fixture_contract_pass(self) -> None:
        subprocess.run(["bash", "-n", str(VERIFIER)], check=True, cwd=ROOT)
        result = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("G002 TS-01 exact consumer-rule source: PASS", result.stdout)

    def test_missing_constructor_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = self.copy_rules(pathlib.Path(temporary))
            copied.write_text(
                copied.read_text(encoding="utf-8").replace(
                    "    <init>(...);\n", ""
                ),
                encoding="utf-8",
            )
            result = self.run_verifier(pathlib.Path(temporary))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact constructor rule once, found 0", result.stderr)

    def test_duplicate_constructor_rule_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = self.copy_rules(pathlib.Path(temporary))
            with copied.open("a", encoding="utf-8") as stream:
                stream.write(f"\n{EXPECTED_RULE}\n")
            result = self.run_verifier(pathlib.Path(temporary))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact constructor rule once, found 2", result.stderr)

    def test_broad_annotated_member_keep_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = self.copy_rules(pathlib.Path(temporary))
            with copied.open("a", encoding="utf-8") as stream:
                stream.write(
                    "\n-keep @io.realm.annotations.RealmModule class * {\n"
                    "    *;\n"
                    "}\n"
                )
            result = self.run_verifier(pathlib.Path(temporary))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broad annotated-class member keep", result.stderr)

    def test_packaged_proguard_entry_requires_exact_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = pathlib.Path(temporary)
            archive = temporary_path / "realm-android-library.aar"
            extracted = temporary_path / "proguard.txt"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("proguard.txt", f"{EXPECTED_RULE}\n")

            subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; extract_packaged_rules "$2" "$3"; '
                    'verify_exact_rule "test AAR" "$3"',
                    "g002-test",
                    str(VERIFIER),
                    str(archive),
                    str(extracted),
                ],
                check=True,
                cwd=ROOT,
            )

            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(
                    "proguard.txt",
                    "-keep @io.realm.annotations.RealmModule class *\n",
                )
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; extract_packaged_rules "$2" "$3"; '
                    'verify_exact_rule "test AAR" "$3"',
                    "g002-test",
                    str(VERIFIER),
                    str(archive),
                    str(extracted),
                ],
                check=False,
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact constructor rule once, found 0", result.stderr)


if __name__ == "__main__":
    unittest.main()
