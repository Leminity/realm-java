#!/usr/bin/env python3
"""Mock-only regression tests for the protected Portal stage/release split."""

from __future__ import annotations

import hashlib
import importlib.util
import json
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

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_bound_bundle(self) -> tuple[Path, Path]:
        files = {
            "io/github/leminity/realm/realm-annotations/10.19.0-agp9.1/realm-annotations-10.19.0-agp9.1.jar": b"jar",
            "io/github/leminity/realm/realm-annotations/10.19.0-agp9.1/realm-annotations-10.19.0-agp9.1.pom": b"pom",
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

    def _stage(self, transport: MockTransport, *, allow_network: bool = True) -> tuple[dict[str, object], Path]:
        stage_manifest = self.root / "stage-manifest.json"
        client = CP.PortalClient(SECRET, transport=transport, sleep=lambda _: None)
        result = CP.stage(
            bundle=self.bundle,
            source_manifest=self.source_manifest,
            tag="v10.19.0-agp9.1",
            version="10.19.0-agp9.1",
            commit=COMMIT,
            core_commit=CORE_COMMIT,
            stage_manifest=stage_manifest,
            token_env="UNUSED",
            allow_network=allow_network,
            attempts=3,
            delay_seconds=0,
            client=client,
        )
        return dict(result), stage_manifest

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
        self.assertEqual(manifest["validation_state_trace"][-1]["state"], "VALIDATED")
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
        result = CP.release(
            stage_manifest=stage_manifest,
            stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
            token_env="UNUSED",
            allow_network=True,
            attempts=3,
            delay_seconds=0,
            client=release_client,
        )
        self.assertEqual(result, {"deployment_id": "deployment-123", "state": "PUBLISHED"})
        self.assertEqual(release_transport.calls[0][1], "https://central.sonatype.com/api/v1/publisher/status?id=deployment-123")
        self.assertEqual(release_transport.calls[1][1], "https://central.sonatype.com/api/v1/publisher/deployment/deployment-123")
        self.assertTrue(all("deployment-123" in call[1] for call in release_transport.calls))

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
            )
        self.assertEqual(rejected_transport.calls, [])

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
            ]
        )
        with self.assertRaises(CP.DeploymentFailed):
            self._stage(transport)
        failure_path = self.root / "stage-manifest.json.failed.json"
        first = failure_path.read_text(encoding="utf-8")
        self.assertIn('"observed_state":"FAILED"', first)
        self.assertNotIn(SECRET, first)
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


if __name__ == "__main__":
    unittest.main()
