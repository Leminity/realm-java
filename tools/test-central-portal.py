#!/usr/bin/env python3
"""Mock-only regression tests for the protected Portal stage/release split."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("central_portal", ROOT / "tools" / "central-portal.py")
assert SPEC and SPEC.loader
CP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CP
SPEC.loader.exec_module(CP)

SECRET = "cG9ydGFsLXVzZXI6cG9ydGFsLXBhc3M="
COMMIT = "a" * 40
CORE_COMMIT = "b" * 40
CI_ARTIFACT_SHA256 = "e" * 64
CI_RUN_ID = "123456"
CI_ARTIFACT_ID = "789012"


class MockTransport:
    def __init__(self, responses: list[CP.HttpResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], data: bytes | None) -> CP.HttpResponse:
        self.calls.append((method, url, dict(headers), data))
        if not self.responses:
            raise AssertionError(f"unexpected Portal request {method} {url}")
        return self.responses.pop(0)


class CentralPortalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.bundle, self.source_manifest = self._write_bound_bundle()
        self.runtime_provenance = self.root / "runtime-provenance.json"
        self.runtime_provenance.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "manifest_kind": "runtime",
                    "source": {
                        "current_head_commit": COMMIT,
                        "core_commit": CORE_COMMIT,
                        "core_gitlink": CORE_COMMIT,
                        "core_submodules": {
                            "external/catch": "1" * 40,
                            "src/external/sha-1": "2" * 40,
                            "src/external/sha-2": "3" * 40,
                        },
                    },
                    "wsl": {"runtime_sha256": "c" * 64, "environment_sha256": "d" * 64},
                    "ci": {
                        "tree_sha256": "4" * 64,
                        "checksum_manifest_sha256": "5" * 64,
                        "checksum_verified": True,
                        "required_exact": ["toolchain/verification.txt"],
                        "required_prefixes": ["ac08/"],
                        "files": {"toolchain/verification.txt": "6" * 64},
                    },
                    "gate_digests": {path: "7" * 64 for path in CP.RUNTIME_GATE_PATHS},
                }
            ),
            encoding="utf-8",
        )
        self.stage_policy = self.root / "stage-policy.json"
        self.release_policy = self.root / "release-policy.json"
        for path, reviewer in ((self.stage_policy, "stage-reviewer"), (self.release_policy, "release-reviewer")):
            path.write_text(
                json.dumps(
                {
                    "deployment_branch_policy": {"protected_branches": True},
                    # This is the nested shape returned by GitHub's GET
                    # environment REST endpoint, not a made-up top-level
                    # prevent_self_review field.
                    "protection_rules": [
                        {
                            "id": 1,
                            "node_id": "MDQ6UmVxdWlyZWRSZXZpZXdlcnMx",
                            "type": "required_reviewers",
                            "prevent_self_review": True,
                            "reviewers": [
                                {"type": "User", "reviewer": {"id": reviewer, "login": reviewer}}
                            ],
                        }
                    ],
                    }
                ),
                encoding="utf-8",
            )
        self.policy_audit = self.root / "policy-audit.json"
        CP.write_environment_policy_audit(self.stage_policy, self.release_policy, self.policy_audit)
        self.consumer_command = self.root / "g011-deployment-consumer.sh"
        self.consumer_command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_bound_bundle(self) -> tuple[Path, Path]:
        files = {
            "io/github/leminity/realm/realm-annotations/10.19.0-agp9.1/realm-annotations-10.19.0-agp9.1.jar": b"jar",
            "io/github/leminity/realm/realm-annotations/10.19.0-agp9.1/realm-annotations-10.19.0-agp9.1.pom": b"pom",
            "io/github/leminity/realm/realm-android-library/10.19.0-agp9.1/realm-android-library-10.19.0-agp9.1.aar": b"public-aar",
        }
        source_manifest = self.root / "source-manifest.json"
        source_manifest.write_text(
            json.dumps(
                {
                    "format": "g008-local-maven-central-inputs-v1",
                    "files": [
                        {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                        for path, data in sorted(files.items())
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        bundle = self.root / "bundle.zip"
        with zipfile.ZipFile(bundle, "w") as archive:
            for path, data in files.items():
                archive.writestr(path, data)
        return bundle, source_manifest

    def _stage(
        self,
        transport: MockTransport,
        *,
        allow_network: bool = True,
        consumer_runner: object | None = None,
    ) -> tuple[dict[str, object], Path]:
        stage_manifest = self.root / "stage-manifest.json"
        client = CP.PortalClient(SECRET, transport=transport, sleep=lambda _: None)
        result = CP.stage(
            bundle=self.bundle,
            source_manifest=self.source_manifest,
            tag="v10.19.0-agp9.1",
            version="10.19.0-agp9.1",
            commit=COMMIT,
            core_commit=CORE_COMMIT,
            runtime_provenance=self.runtime_provenance,
            ci_artifact_sha256=CI_ARTIFACT_SHA256,
            ci_run_id=CI_RUN_ID,
            ci_artifact_id=CI_ARTIFACT_ID,
            environment_policy_audit=self.policy_audit,
            validated_consumer_command=self.consumer_command,
            validated_consumer_gradle_home=self.root / "validated-home",
            validated_consumer_evidence=self.root / "validated-evidence",
            stage_manifest=stage_manifest,
            token_env="UNUSED",
            allow_network=allow_network,
            attempts=3,
            delay_seconds=0,
            client=client,
            consumer_runner=consumer_runner or self._consumer_runner,
        )
        return dict(result), stage_manifest

    @staticmethod
    def _consumer_runner(args: list[str]) -> None:
        evidence = Path(args[args.index("--evidence-dir") + 1])
        repository = args[args.index("--repository-url") + 1]
        mode = args[args.index("--mode") + 1]
        evidence.mkdir(parents=True, exist_ok=True)
        checksums = evidence / "SHA256SUMS"
        checksums.write_text("consumer PASS\n", encoding="utf-8")
        (evidence / "consumer-evidence.json").write_text(
            json.dumps(
                {
                    "format": CP.CONSUMER_EVIDENCE_FORMAT,
                    "mode": mode,
                    "repository_url": repository,
                    "exact_six": "PASS",
                    "ac08": "PASS",
                    "native_elf": "PASS",
                    "sha256sums_sha256": hashlib.sha256(checksums.read_bytes()).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

    def test_stage_is_one_user_managed_upload_and_never_publishes(self) -> None:
        transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"PENDING"}'),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        result, stage_manifest = self._stage(transport)
        self.assertEqual(result["deployment_id"], "deployment-123")
        self.assertEqual(len(transport.calls), 3)
        upload_url = transport.calls[0][1]
        self.assertEqual(urlparse(upload_url).path, "/api/v1/publisher/upload")
        self.assertEqual(parse_qs(urlparse(upload_url).query), {"name": ["v10.19.0-agp9.1"], "publishingType": ["USER_MANAGED"]})
        self.assertTrue(all("/status?id=deployment-123" in call[1] for call in transport.calls[1:]))
        self.assertFalse(any(call[1].endswith("/api/v1/publisher/deployment/deployment-123") for call in transport.calls))
        self.assertEqual(transport.calls[0][2]["Authorization"], f"Bearer {SECRET}")
        manifest_text = stage_manifest.read_text(encoding="utf-8")
        self.assertNotIn(SECRET, manifest_text)
        manifest = json.loads(manifest_text)
        self.assertEqual(manifest["publishing_type"], "USER_MANAGED")
        self.assertEqual(manifest["ci_artifact_sha256"], CI_ARTIFACT_SHA256)
        self.assertEqual(manifest["ci_run_id"], CI_RUN_ID)
        self.assertEqual(manifest["ci_artifact_id"], CI_ARTIFACT_ID)
        self.assertEqual(manifest["validation_state_trace"][-1]["state"], "VALIDATED")
        self.assertEqual(
            manifest["realm_android_library_aar_sha256"], hashlib.sha256(b"public-aar").hexdigest()
        )
        self.assertEqual(
            manifest["deployment_repository"],
            "https://central.sonatype.com/api/v1/publisher/deployment/deployment-123/download/{relative_path}",
        )

    def test_stage_refuses_network_without_explicit_opt_in(self) -> None:
        transport = MockTransport([])
        stage_manifest = self.root / "blocked-stage-manifest.json"
        client = CP.PortalClient(SECRET, transport=transport, sleep=lambda _: None)
        with self.assertRaisesRegex(CP.PortalError, "requires --allow-network") as raised:
            CP.stage(
                bundle=self.bundle,
                source_manifest=self.source_manifest,
                tag="v10.19.0-agp9.1",
                version="10.19.0-agp9.1",
                commit=COMMIT,
                core_commit=CORE_COMMIT,
                runtime_provenance=self.runtime_provenance,
                ci_artifact_sha256=CI_ARTIFACT_SHA256,
                ci_run_id=CI_RUN_ID,
                ci_artifact_id=CI_ARTIFACT_ID,
                environment_policy_audit=self.policy_audit,
                validated_consumer_command=self.consumer_command,
                validated_consumer_gradle_home=self.root / "blocked-home",
                validated_consumer_evidence=self.root / "blocked-evidence",
                stage_manifest=stage_manifest,
                token_env="UNUSED",
                allow_network=False,
                attempts=1,
                delay_seconds=0,
                client=client,
            )
        self.assertEqual(transport.calls, [])
        self.assertNotIn(SECRET, str(raised.exception))

    def test_release_requires_immutable_manifest_hash_and_exact_deployment(self) -> None:
        stage_transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        stage_result, stage_manifest = self._stage(stage_transport)
        release_transport = MockTransport(
            [
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
                CP.HttpResponse(204, b""),
                CP.HttpResponse(200, b'{"deploymentState":"PUBLISHING"}'),
                CP.HttpResponse(200, b'{"deploymentState":"PUBLISHED"}'),
            ]
        )
        release_client = CP.PortalClient(SECRET, transport=release_transport, sleep=lambda _: None)
        consumer_args: list[str] = []

        def capture_consumer(args: list[str]) -> None:
            consumer_args[:] = args
            self._consumer_runner(args)

        result = CP.release(
            stage_manifest=stage_manifest,
            stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
            token_env="UNUSED",
            allow_network=True,
            attempts=3,
            delay_seconds=0,
            client=release_client,
            published_consumer_command=self.consumer_command,
            published_consumer_gradle_home=self.root / "central-home",
            published_consumer_evidence=self.root / "central-evidence",
            consumer_runner=capture_consumer,
        )
        self.assertEqual(result["deployment_id"], "deployment-123")
        self.assertEqual(result["state"], "PUBLISHED")
        self.assertEqual(release_transport.calls[0][1], "https://central.sonatype.com/api/v1/publisher/status?id=deployment-123")
        self.assertEqual(release_transport.calls[1][1], "https://central.sonatype.com/api/v1/publisher/deployment/deployment-123")
        self.assertTrue(all("deployment-123" in call[1] for call in release_transport.calls))
        self.assertEqual(
            consumer_args[consumer_args.index("--expected-realm-android-library-sha256") + 1],
            hashlib.sha256(b"public-aar").hexdigest(),
        )

        rejected_transport = MockTransport([])
        with self.assertRaisesRegex(CP.PortalError, "SHA-256 mismatch"):
            CP.release(
                stage_manifest=stage_manifest,
                stage_manifest_sha256="0" * 64,
                token_env="UNUSED",
                allow_network=True,
                attempts=1,
                delay_seconds=0,
                client=CP.PortalClient(SECRET, transport=rejected_transport, sleep=lambda _: None),
                published_consumer_command=self.consumer_command,
                published_consumer_gradle_home=self.root / "central-home-rejected",
                published_consumer_evidence=self.root / "central-evidence-rejected",
                consumer_runner=self._consumer_runner,
            )
        self.assertEqual(rejected_transport.calls, [])

    def test_release_resume_after_published_skips_second_publish(self) -> None:
        stage_transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        stage_result, stage_manifest = self._stage(stage_transport)
        release_transport = MockTransport([CP.HttpResponse(200, b'{"deploymentState":"PUBLISHED"}')])
        result = CP.release(
            stage_manifest=stage_manifest,
            stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
            token_env="UNUSED",
            allow_network=True,
            attempts=2,
            delay_seconds=0,
            client=CP.PortalClient(SECRET, transport=release_transport, sleep=lambda _: None),
            published_consumer_command=self.consumer_command,
            published_consumer_gradle_home=self.root / "resume-home",
            published_consumer_evidence=self.root / "resume-evidence",
            consumer_runner=self._consumer_runner,
        )
        self.assertEqual(result["state"], "PUBLISHED")
        self.assertEqual(len(release_transport.calls), 1)
        self.assertIn("/status?id=deployment-123", release_transport.calls[0][1])

    def test_runtime_provenance_rejects_legacy_ad_hoc_schema(self) -> None:
        legacy = self.root / "legacy-runtime.json"
        legacy.write_text(
            json.dumps(
                {
                    "source": {"head": COMMIT, "core_gitlink": CORE_COMMIT},
                    "wsl": {"runtime_sha256": "c" * 64},
                    "ci": {"evidence_sha256": "d" * 64},
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CP.PortalError, "unsupported schema"):
            CP.verify_runtime_provenance(legacy, COMMIT, CORE_COMMIT)

    def test_stage_cli_parses_only_stage_arguments_and_fails_closed_without_network(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "central-portal.py"),
                "stage",
                "--bundle",
                str(self.bundle),
                "--source-manifest",
                str(self.source_manifest),
                "--tag",
                "v10.19.0-agp9.1",
                "--version",
                "10.19.0-agp9.1",
                "--commit",
                COMMIT,
                "--core-commit",
                CORE_COMMIT,
                "--runtime-provenance",
                str(self.runtime_provenance),
                "--ci-artifact-sha256",
                CI_ARTIFACT_SHA256,
                "--ci-run-id",
                CI_RUN_ID,
                "--ci-artifact-id",
                CI_ARTIFACT_ID,
                "--environment-policy-audit",
                str(self.policy_audit),
                "--validated-consumer-command",
                str(self.consumer_command),
                "--validated-consumer-gradle-home",
                str(self.root / "cli-stage-home"),
                "--validated-consumer-evidence",
                str(self.root / "cli-stage-evidence"),
                "--stage-manifest",
                str(self.root / "cli-stage-manifest.json"),
            ],
            check=False,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn("network access requires --allow-network", completed.stderr)
        self.assertNotIn("AttributeError", completed.stderr)

    def test_release_cli_parses_and_wires_required_published_consumer_arguments(self) -> None:
        stage_transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        stage_result, stage_manifest = self._stage(stage_transport)
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "central-portal.py"),
                "release",
                "--stage-manifest",
                str(stage_manifest),
                "--stage-manifest-sha256",
                str(stage_result["stage_manifest_sha256"]),
                "--published-consumer-command",
                str(self.consumer_command),
                "--published-consumer-gradle-home",
                str(self.root / "cli-release-home"),
                "--published-consumer-evidence",
                str(self.root / "cli-release-evidence"),
            ],
            check=False,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn("network access requires --allow-network", completed.stderr)
        self.assertNotIn("TypeError", completed.stderr)

    def test_poll_is_bounded_and_preserves_first_terminal_failure(self) -> None:
        transport = MockTransport(
            [
                CP.HttpResponse(200, b'{"deploymentState":"PENDING"}'),
                CP.HttpResponse(200, b'{"deploymentState":"PENDING"}'),
            ]
        )
        client = CP.PortalClient(SECRET, transport=transport, sleep=lambda _: None)
        with self.assertRaisesRegex(CP.PortalError, "bounded polling"):
            client.poll("deployment-123", "VALIDATED", attempts=2, delay_seconds=0)
        self.assertEqual(len(transport.calls), 2)

        failure_transport = MockTransport([CP.HttpResponse(200, b'{"deploymentState":"FAILED"}')])
        failure_client = CP.PortalClient(SECRET, transport=failure_transport, sleep=lambda _: None)
        with self.assertRaisesRegex(CP.PortalError, "did not reach expected VALIDATED state"):
            failure_client.poll("deployment-123", "VALIDATED", attempts=3, delay_seconds=0)
        self.assertEqual(len(failure_transport.calls), 1)

    def test_stage_preserves_redacted_first_failed_status(self) -> None:
        transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"FAILED"}'),
                CP.HttpResponse(204, b""),
            ]
        )
        with self.assertRaises(CP.DeploymentFailed):
            self._stage(transport)
        failure_path = self.root / "stage-manifest.json.failed.json"
        first = failure_path.read_text(encoding="utf-8")
        self.assertIn('"observed_state":"FAILED"', first)
        self.assertNotIn(SECRET, first)
        self.assertEqual(transport.calls[-1][0], "DELETE")
        self.assertTrue(transport.calls[-1][1].endswith("/deployment/deployment-123"))
        failure_path.write_text("first-failure-is-immutable", encoding="utf-8")
        CP._write_first_failure(
            self.root / "stage-manifest.json",
            deployment_id="deployment-123",
            expected="VALIDATED",
            state="FAILED",
            bundle_sha256="a" * 64,
            source_manifest_sha256="b" * 64,
        )
        self.assertEqual(failure_path.read_text(encoding="utf-8"), "first-failure-is-immutable")

    def test_stage_refuses_a_second_upload_for_same_manifest_path(self) -> None:
        transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        _, stage_manifest = self._stage(transport)
        retry_transport = MockTransport([])
        with self.assertRaisesRegex(CP.PortalError, "already has an upload outcome"):
            self._stage(retry_transport)
        self.assertTrue(stage_manifest.is_file())
        self.assertEqual(retry_transport.calls, [])

    def test_consumer_failure_is_a_first_upload_outcome_and_blocks_retry(self) -> None:
        transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
                CP.HttpResponse(204, b""),
            ]
        )

        def fail_consumer(_: list[str]) -> None:
            raise CP.PortalError("consumer gate failed")

        with self.assertRaisesRegex(CP.PortalError, "consumer gate failed"):
            self._stage(transport, consumer_runner=fail_consumer)
        failure_path = self.root / "stage-manifest.json.failed.json"
        evidence = json.loads(failure_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["deployment_id"], "deployment-123")
        self.assertEqual(evidence["expected_state"], "CONSUMER_PASS")
        self.assertEqual(transport.calls[-1][0], "DELETE")
        self.assertTrue(transport.calls[-1][1].endswith("/deployment/deployment-123"))
        retry = MockTransport([])
        with self.assertRaisesRegex(CP.PortalError, "already has an upload outcome"):
            self._stage(retry)
        self.assertEqual(retry.calls, [])

    def test_client_rejects_non_base64_username_password_credential(self) -> None:
        with self.assertRaisesRegex(CP.PortalError, "credential is invalid"):
            CP.PortalClient("not-base64", transport=MockTransport([]))

    def test_retry_after_overrides_configured_backoff(self) -> None:
        delays: list[float] = []
        transport = MockTransport(
            [
                CP.HttpResponse(200, b'{"deploymentState":"PENDING"}', {"Retry-After": "7"}),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        client = CP.PortalClient(SECRET, transport=transport, sleep=delays.append)
        self.assertEqual(
            client.poll(
                "deployment-123",
                "VALIDATED",
                attempts=2,
                delay_seconds=1,
                backoff_factor=2,
                max_delay_seconds=3,
            ),
            "VALIDATED",
        )
        self.assertEqual(delays, [7.0])

    def test_binding_rejects_wrong_tag_and_bundle_content(self) -> None:
        with self.assertRaisesRegex(CP.PortalError, "approved release family"):
            CP.validate_release_binding("v10.19.0-agp9.0", "10.19.0-agp9.0", COMMIT, CORE_COMMIT)
        source = json.loads(self.source_manifest.read_text(encoding="utf-8"))
        source["files"][0]["sha256"] = "0" * 64
        self.source_manifest.write_text(json.dumps(source), encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "digest differs"):
            CP.verify_bundle_binding(self.bundle, self.source_manifest)
        self.bundle, self.source_manifest = self._write_bound_bundle()
        with zipfile.ZipFile(self.bundle, "a") as archive:
            archive.writestr("unexpected.txt", b"unexpected")
        with self.assertRaisesRegex(CP.PortalError, "paths differ"):
            CP.verify_bundle_binding(self.bundle, self.source_manifest)

    def test_policy_audit_is_redacted_hashed_and_requires_independent_reviewers(self) -> None:
        audit_sha = CP.verify_environment_policy_audit(self.policy_audit)
        self.assertEqual(audit_sha, CP.sha256_file(self.policy_audit))
        audit = self.policy_audit.read_text(encoding="utf-8")
        self.assertNotIn("stage-reviewer", audit)
        self.assertNotIn("release-reviewer", audit)
        duplicate = self.root / "duplicate-release-policy.json"
        duplicate.write_text(self.stage_policy.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "not distinct"):
            CP.write_environment_policy_audit(self.stage_policy, duplicate, self.root / "duplicate-audit.json")
        policy = json.loads(self.stage_policy.read_text(encoding="utf-8"))
        policy["protection_rules"][0]["prevent_self_review"] = False
        missing_self_review = self.root / "missing-self-review.json"
        missing_self_review.write_text(json.dumps(policy), encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "prevent-self-review"):
            CP.write_environment_policy_audit(missing_self_review, self.release_policy, self.root / "missing-self-review-audit.json")

    def test_workflow_has_only_release_published_trigger_and_protected_split(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("release:\n    types: [published]", workflow)
        self.assertNotIn("workflow_dispatch", workflow)
        self.assertIn("environment: maven-central-stage", workflow)
        self.assertIn("environment: maven-central-release", workflow)
        self.assertIn('"publishingType": "USER_MANAGED"', (ROOT / "tools" / "central-portal.py").read_text(encoding="utf-8"))
        self.assertIn("actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683", workflow)
        self.assertIn("github.event.release.prerelease == false", workflow)
        self.assertIn('test "$GITHUB_REF" = "refs/tags/$TAG"', workflow)
        self.assertNotIn("tools/release.sh", workflow)
        self.assertIn("G011_ENVIRONMENT_POLICY_TOKEN", workflow)
        self.assertIn("audit-environment-policy", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("group: realm-central-${{ github.event.release.tag_name }}", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("if: ${{ always() }}", workflow)
        self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", workflow)
        self.assertIn("g011-central-stage-evidence-${{ github.run_id }}-${{ github.run_attempt }}", workflow)
        self.assertIn("maven-central-stage-manifest.json.failed.json", workflow)
        release_job = workflow[workflow.index("\n  release:\n    name:") :]
        self.assertLess(
            release_job.index('test -z "$(git status --porcelain --untracked-files=all)"'),
            release_job.index('printf \'%s\' "$STAGE_MANIFEST_B64"'),
        )
        self.assertNotIn("build/g011-runtime-provenance.json", workflow)
        self.assertNotIn("realm-g011-runtime-provenance-v1", workflow)
        self.assertIn("g011-ci-evidence-{commit}", workflow)
        self.assertIn("CI artifact lacks an exact SHA-256 digest", workflow)
        self.assertIn("--ci-artifact-sha256", workflow)
        self.assertIn("--ci-run-id", workflow)
        self.assertIn("--ci-artifact-id", workflow)
        self.assertEqual(workflow.count("--mode runtime"), 2)
        self.assertGreaterEqual(workflow.count("--runtime-evidence-dir"), 2)
        self.assertEqual(workflow.count('test "$actual_archive_sha" = "$expected_archive_sha"'), 1)
        self.assertEqual(workflow.count('= "$expected_archive_sha"'), 2)
        self.assertIn('test "$stage_tag" = "$TAG"', release_job)
        self.assertIn('test "$stage_version" = "$(tr -d \'[:space:]\' < version.txt)"', release_job)
        self.assertIn("--validated-consumer-command", workflow)
        self.assertIn("--published-consumer-command", workflow)
        self.assertLess(release_job.index("actions/checkout@"), release_job.index("tools/central-portal.py release"))
        self.assertIn("g011-consume-six.sh", workflow)
        self.assertIn("compatibility-fixtures/ac08-api37-ps16k-runtime/run-ac08.sh", workflow)
        self.assertIn("g011-verify-native-elf.sh", workflow)
        self.assertEqual(workflow.count("runs-on: [self-hosted, linux, api37, ps16k]"), 2)
        self.assertGreaterEqual(workflow.count("Preflight the trusted API37/ps16k runner contract"), 2)
        self.assertIn("adb -s emulator-5654 wait-for-device", workflow)
        self.assertNotIn("emulator-5554", workflow)
        self.assertIn("pm.16kb.app_compat.disabled", workflow)
        self.assertNotIn("pm.16kb.app_compat.package_enabled", workflow)
        self.assertIn("g008SigningKey: ${{ secrets.MAVEN_SIGNING_KEY }}", workflow)
        self.assertNotIn("ORG_GRADLE_PROJECT_signingKey", workflow)
        self.assertIn("getconf PAGE_SIZE", workflow)
        self.assertIn("--expected-realm-android-library-sha256", workflow)
        self.assertIn("realm-android-library-$version.aar", release_job)
        self.assertIn("sha256sum -c -", release_job)
        self.assertIn("g011-verify-native-elf.sh --aar \"$aar\"", release_job)
        self.assertIn("https://repo.maven.apache.org/maven2", workflow)
        self.assertNotIn("https://repo1.maven.org/maven2", workflow)
        self.assertNotIn("build/g008-maven-central-bundle.zip", release_job)
        self.assertNotIn("find . -type f -printf '%P\\0' | sort -z | xargs -0 sha256sum > SHA256SUMS", workflow)
        self.assertGreaterEqual(workflow.count("! -name SHA256SUMS ! -name checksum-verify.log"), 2)
        self.assertGreaterEqual(workflow.count("rm -f SHA256SUMS checksum-verify.log"), 2)
        self.assertGreaterEqual(workflow.count("sha256sum -c SHA256SUMS > checksum-verify.log"), 2)
        legacy = (ROOT / "tools" / "release.sh").read_text(encoding="utf-8")
        self.assertIn("Protected Maven Central release GitHub workflow", legacy)
        self.assertNotIn("mavenCentralUpload", legacy)


if __name__ == "__main__":
    unittest.main()
