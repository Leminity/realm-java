#!/usr/bin/env python3
"""Regression tests for the GitHub Actions runner trust boundary."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
TRUSTED_BRANCH = "agp9.1"
GITHUB_HOSTED_UBUNTU = re.compile(r"^ubuntu-(?:latest|\d+\.\d+)$")


def top_level_block(text: str, key: str) -> str:
    """Return one small top-level YAML block without needing a YAML package."""
    lines = text.splitlines()
    header = re.compile(rf"^(?:['\"]?{re.escape(key)}['\"]?):(?:\s*(.*))?$")
    for index, line in enumerate(lines):
        match = header.match(line)
        if not match:
            continue
        inline = (match.group(1) or "").strip()
        if inline:
            return inline
        block: list[str] = []
        for child in lines[index + 1 :]:
            if child and not child[0].isspace():
                break
            block.append(child)
        return "\n".join(block)
    raise AssertionError(f"missing top-level {key!r} block")


def has_trigger(text: str, event: str) -> bool:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_-]*", top_level_block(text, "on"))
    return event in tokens


def job_blocks(text: str) -> dict[str, str]:
    jobs = top_level_block(text, "jobs").splitlines()
    headers = [
        (index, match.group(1))
        for index, line in enumerate(jobs)
        if (match := re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line))
    ]
    result: dict[str, str] = {}
    for offset, (index, name) in enumerate(headers):
        end = headers[offset + 1][0] if offset + 1 < len(headers) else len(jobs)
        result[name] = "\n".join(jobs[index:end])
    if not result:
        raise AssertionError("workflow contains no statically inspectable jobs")
    return result


def runs_on(job: str) -> str:
    match = re.search(r"^    runs-on:\s*(.+?)\s*$", job, re.MULTILINE)
    if not match:
        raise AssertionError("job must declare a literal runs-on value")
    return match.group(1).split("#", 1)[0].strip()


class WorkflowTrustTests(unittest.TestCase):
    def test_every_pull_request_job_uses_github_hosted_ubuntu(self) -> None:
        checked_jobs = 0
        for workflow in sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml"))):
            text = workflow.read_text(encoding="utf-8")
            if not (has_trigger(text, "pull_request") or has_trigger(text, "pull_request_target")):
                continue
            for job_name, job in job_blocks(text).items():
                runner = runs_on(job)
                self.assertRegex(
                    runner,
                    GITHUB_HOSTED_UBUNTU,
                    f"{workflow.name}:{job_name} is PR-reachable on non-ephemeral runner {runner!r}",
                )
                checked_jobs += 1
        self.assertGreater(checked_jobs, 0)

    def test_full_ci_is_trusted_branch_push_only(self) -> None:
        workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        triggers = top_level_block(workflow, "on")
        self.assertTrue(has_trigger(workflow, "push"))
        self.assertFalse(has_trigger(workflow, "pull_request"))
        self.assertFalse(has_trigger(workflow, "pull_request_target"))
        self.assertEqual(re.findall(r"(?m)^  ([A-Za-z_][A-Za-z0-9_-]*):\s*$", triggers), ["push"])
        self.assertEqual(re.findall(r"(?m)^      - ([A-Za-z0-9._/-]+)\s*$", triggers), [TRUSTED_BRANCH])
        self.assertEqual(runs_on(job_blocks(workflow)["provenance-and-gates"]), "[self-hosted, linux, api37, ps16k]")

    def test_pull_request_validation_is_focused_and_unprivileged(self) -> None:
        workflow = (WORKFLOWS / "pull-request.yml").read_text(encoding="utf-8")
        self.assertTrue(has_trigger(workflow, "pull_request"))
        self.assertFalse(has_trigger(workflow, "pull_request_target"))
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertEqual(runs_on(job_blocks(workflow)["workflow-trust-boundary"]), "ubuntu-latest")
        self.assertIn("actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683", workflow)
        self.assertIn("python3 tools/test-g013-workflow-trust.py", workflow)


if __name__ == "__main__":
    unittest.main()
