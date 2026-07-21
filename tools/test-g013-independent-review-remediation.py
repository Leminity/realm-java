#!/usr/bin/env python3
"""Regression checks for the G013 independent-review remediation."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_ROOT = "0ab8d6961afb038d0e0c69478de45dda3958d641"
REVIEW_ROOT = "117f0bee2cdea2c4bf75c7d3226dd389a21439bc"
MODIFICATION_NOTICE = "Modified by Leminity from the upstream Realm Java project."
FORMAT_CONSTRAINED = {
    "version.txt",
}
CORE_GITLINK = "realm/realm-library/src/main/cpp/realm-core"


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True
    ).strip()


class IndependentReviewRemediationTests(unittest.TestCase):
    def test_every_upstream_modified_text_file_carries_notice(self) -> None:
        modified = set(
            git(
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "--diff-filter=M",
                UPSTREAM_ROOT,
                REVIEW_ROOT,
            ).splitlines()
        )
        self.assertEqual(37, len(modified))
        self.assertTrue(FORMAT_CONSTRAINED <= modified)
        self.assertIn(CORE_GITLINK, modified)

        for relative in sorted(modified - FORMAT_CONSTRAINED - {CORE_GITLINK}):
            with self.subTest(path=relative):
                contents = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(MODIFICATION_NOTICE, contents)

    def test_notice_records_inline_policy_and_format_constrained_files(self) -> None:
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("Apache License 2.0 section 4(b)", notice)
        self.assertIn(MODIFICATION_NOTICE, notice)
        for relative in sorted(FORMAT_CONSTRAINED):
            self.assertIn(relative, notice)
        self.assertIn("locally modified Realm Core source", notice)
        self.assertIn("c97091234d40efaaaf7d8d8349eb3c97012f6c9b", notice)
        self.assertIn("d7b52ccbada0283527db36143cfeab18692b4ed0", notice)
        self.assertIn(CORE_GITLINK, notice)

    def test_readme_identifies_the_fork_before_upstream_project_context(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        first_line = next(line for line in readme.splitlines() if line.strip())
        self.assertEqual("# Realm Java — Leminity maintenance fork", first_line)
        self.assertIn(MODIFICATION_NOTICE, readme)
        self.assertIn("io.github.leminity.realm/realm-gradle-plugin", readme)
        self.assertIn("https://github.com/Leminity/realm-java/blob/agp9.1/LICENSE", readme)
        self.assertIn("git clone https://github.com/Leminity/realm-java.git", readme)
        self.assertNotIn("git clone git@github.com:realm/realm-java.git", readme)
        self.assertNotIn("git clone https://github.com/realm/realm-java.git", readme)

    def test_python_bytecode_is_ignored_and_not_tracked(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("__pycache__/", ignore)
        self.assertIn("*.py[cod]", ignore)
        tracked = git("ls-files", "*.pyc", "*.pyo", "*.pyd", "**/__pycache__/*")
        self.assertEqual("", tracked)

    def test_baseline_verifier_uses_exact_review_root_and_tree_only_diff(self) -> None:
        verifier = (ROOT / "tools/verify-baseline.sh").read_text(encoding="utf-8")
        self.assertIn(f"readonly EXPECTED_APPROVED_FORK_ROOT={REVIEW_ROOT}", verifier)
        self.assertIn("git diff-tree", verifier)
        self.assertNotIn('git diff --name-only "$EXPECTED_COMMIT...HEAD"', verifier)
        self.assertIn('git rev-parse "HEAD:$core"', verifier)

    def test_apache_license_text_is_preserved(self) -> None:
        current = git("hash-object", "LICENSE")
        upstream = git("rev-parse", f"{UPSTREAM_ROOT}:LICENSE")
        self.assertEqual(upstream, current)


if __name__ == "__main__":
    unittest.main()
