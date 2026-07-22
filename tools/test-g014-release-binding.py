#!/usr/bin/env python3
"""Adversarial regressions for the G014 canonical release rebind."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
STALE_RELEASE_COMMIT = "9b952eb0c55c280128a9fee910274b6f906fa051"
STALE_CORE_COMMIT = "d7b52ccbada0283527db36143cfeab18692b4ed0"


class G014ReleaseBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.stage_job, release_tail = cls.workflow.split(
            "\n  release:\n    name: Reviewer-gated Central publication", 1
        )
        cls.release_job = "\n  release:\n    name: Reviewer-gated Central publication" + release_tail
        cls.source_binding = cls.stage_job.split(
            "      - name: Bind approved tag to the checked-out source tree", 1
        )[1].split("      - name: Recover a prior immutable stage outcome", 1)[0]
        cls.stage_recovery = cls.stage_job.split(
            "      - name: Recover a prior immutable stage outcome without re-uploading", 1
        )[1].split("      - name: Download and independently verify exact successful CI evidence", 1)[0]
        cls.final_source = cls.release_job.split(
            "      - name: Rebind final reviewed source to the exact staged deployment immediately before publication",
            1,
        )[1].split("      - name: Write immutable publication intent", 1)[0]
        cls.portal_release = cls.release_job.split(
            "      - name: Publish the exact staged deployment in a Portal-only process", 1
        )[1].split("      - name: Consume Maven Central", 1)[0]

    def test_ac07_wrapper_is_executable_and_stage_outcome_preserves_hidden_files(self) -> None:
        import subprocess

        wrapper = ROOT / "compatibility-fixtures/official-10.19.0-generator/gradlew"
        mode = subprocess.check_output(
            ["git", "ls-files", "--stage", "--", str(wrapper.relative_to(ROOT))],
            cwd=ROOT,
            text=True,
        ).split()[0]
        self.assertEqual(mode, "100755")
        stage_outcome = self.stage_job.split(
            "      - name: Retain immutable redacted stage transaction outcome", 1
        )[1].split("      - name: Retain run-scoped pre-transaction diagnostics", 1)[0]
        self.assertIn("include-hidden-files: true", stage_outcome)

    def test_every_mutating_boundary_uses_fresh_run_scoped_remote_refs(self) -> None:
        self.assertIn("FINAL_SOURCE_BRANCH: agp9.1", self.workflow)
        self.assertGreaterEqual(
            self.workflow.count(
                'refs/g011/final-source/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/'
            ),
            4,
        )
        self.assertGreaterEqual(
            self.workflow.count("git fetch --quiet --force --no-tags origin"), 4
        )
        self.assertGreaterEqual(
            self.workflow.count('"refs/heads/$FINAL_SOURCE_BRANCH:$final_branch_ref"'),
            4,
        )
        self.assertGreaterEqual(
            self.workflow.count('"refs/tags/$TAG:$final_tag_ref"'), 4
        )
        self.assertGreaterEqual(self.workflow.count('git update-ref -d "$final_branch_ref"'), 4)
        self.assertGreaterEqual(self.workflow.count('git update-ref -d "$final_tag_ref"'), 4)
        self.assertNotIn(STALE_RELEASE_COMMIT, self.workflow)
        self.assertNotIn(STALE_CORE_COMMIT, self.workflow)

    def test_actual_tag_commit_and_parent_tree_gitlink_bind_the_stage_source(self) -> None:
        self.assertIn('commit="$(git rev-parse HEAD)"', self.source_binding)
        self.assertIn(
            'test "$commit" = "$(git rev-parse "$final_branch_ref^{commit}")"',
            self.source_binding,
        )
        self.assertIn(
            'test "$commit" = "$(git rev-parse "$final_tag_ref^{commit}")"',
            self.source_binding,
        )
        self.assertIn(
            'core_commit="$(git ls-tree "$commit" "$core_path" | awk \'$1 == "160000" && $2 == "commit" {print $3}\')"',
            self.source_binding,
        )
        self.assertIn(
            'test "$(git -C "$core_path" rev-parse HEAD)" = "$core_commit"',
            self.source_binding,
        )
        self.assertIn(
            'test -z "$(git -C "$core_path" status --porcelain --untracked-files=all)"',
            self.source_binding,
        )

    def test_recovery_requires_exact_tag_version_commit_and_core_binding(self) -> None:
        self.assertIn("CORE_COMMIT: ${{ steps.source.outputs.core_commit }}", self.stage_recovery)
        self.assertIn(
            '--tag "$TAG" --version "$VERSION" --commit "$COMMIT" --core-commit "$CORE_COMMIT"',
            self.stage_recovery,
        )
        self.assertIn(
            "('tag', 'version', 'commit', 'core_commit')", self.stage_recovery
        )
        self.assertIn(
            "prior stage outcome differs from exact source/tag/Core binding",
            self.stage_recovery,
        )
        self.assertIn('name="g011-central-stage-outcome-$COMMIT"', self.stage_recovery)
        self.assertIn(
            "item.get('workflow_run', {}).get('head_sha') == commit",
            self.stage_recovery,
        )

    def test_final_rebind_and_publish_repeat_the_exact_binding_before_network(self) -> None:
        for fragment in (
            'test "$commit" = "$EXPECTED_COMMIT"',
            'test "$commit" = "$(git rev-parse "$final_branch_ref^{commit}")"',
            'test "$commit" = "$(git rev-parse "$final_tag_ref^{commit}")"',
            'test "$core_commit" = "$EXPECTED_CORE_COMMIT"',
            '--tag "$TAG" --version "$version" --commit "$commit" --core-commit "$core_commit"',
        ):
            self.assertIn(fragment, self.final_source)
        for fragment in (
            "git fetch --quiet --force --no-tags origin",
            'test "$commit" = "$EXPECTED_COMMIT"',
            'test "$core_commit" = "$EXPECTED_CORE_COMMIT"',
            '--tag "$TAG" --version "$VERSION" --commit "$commit" --core-commit "$core_commit"',
        ):
            self.assertIn(fragment, self.portal_release)
        final_rebind = self.release_job.index(
            "Rebind final reviewed source to the exact staged deployment immediately before publication"
        )
        intent = self.release_job.index(
            "Write immutable publication intent after reviewer approval and final reaudit"
        )
        publish = self.release_job.index(
            "Publish the exact staged deployment in a Portal-only process"
        )
        self.assertLess(final_rebind, intent)
        self.assertLess(intent, publish)

    def test_user_managed_stage_remains_reversible_and_cannot_publish(self) -> None:
        portal = (ROOT / "tools" / "central-portal.py").read_text(encoding="utf-8")
        self.assertIn(
            'urlencode({"name": name, "publishingType": "USER_MANAGED"})', portal
        )
        self.assertIn("--drop-failed-deployment", self.stage_job)
        self.assertNotIn("tools/central-portal.py release", self.stage_job)
        self.assertIn("environment: maven-central-release", self.release_job)
        self.assertIn("tools/central-portal.py release", self.release_job)


if __name__ == "__main__":
    unittest.main()
