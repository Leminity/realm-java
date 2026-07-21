#!/usr/bin/env python3
"""Mock-only regression tests for the protected Portal stage/release split."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, unquote, urlparse
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
TAG = "v10.19.0-agp9.1"
VERSION = "10.19.0-agp9.1"
BINDING = {
    "tag": TAG,
    "version": VERSION,
    "commit": COMMIT,
    "core_commit": CORE_COMMIT,
}
BINDING_ARGS = [
    "--tag", TAG,
    "--version", VERSION,
    "--commit", COMMIT,
    "--core-commit", CORE_COMMIT,
]
FINAL_COMMIT = "71908d956e5223a51031b2882dee933350fb0324"
FINAL_CORE_COMMIT = "a5b7ed7bb8f0db4d362c7e45b2f38358a4aeab47"
STALE_COMMIT = "9b952eb0c55c280128a9fee910274b6f906fa051"
STALE_CORE_COMMIT = "d7b52ccbada0283527db36143cfeab18692b4ed0"
FINAL_BINDING = {
    "tag": TAG,
    "version": VERSION,
    "commit": FINAL_COMMIT,
    "core_commit": FINAL_CORE_COMMIT,
}
REPOSITORY = "Leminity/realm-java"
GATE_TIME = "2026-07-17T08:00:00Z"


class MockTransport:
    def __init__(self, responses: list[CP.HttpResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []
        self.downloads: dict[str, bytes] = {}

    def __call__(self, method: str, url: str, headers: dict[str, str], data: bytes | None) -> CP.HttpResponse:
        self.calls.append((method, url, dict(headers), data))
        marker = "/download/"
        if method == "GET" and marker in url:
            relative_path = unquote(url.split(marker, 1)[1])
            if relative_path not in self.downloads:
                return CP.HttpResponse(404, b"")
            return CP.HttpResponse(200, self.downloads[relative_path])
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
        self.stage_deployment_policies = self.root / "stage-deployment-policies.json"
        self.release_deployment_policies = self.root / "release-deployment-policies.json"
        deployment_policy = json.dumps(
            {
                "total_count": 1,
                "branch_policies": [
                    {"id": 1, "name": CP.APPROVED_DEPLOYMENT_TAG_PATTERN, "type": "tag"}
                ],
            }
        )
        self.stage_deployment_policies.write_text(deployment_policy, encoding="utf-8")
        self.release_deployment_policies.write_text(deployment_policy, encoding="utf-8")
        for path in (self.stage_policy, self.release_policy):
            path.write_text(
                json.dumps(
                {
                    "deployment_branch_policy": {
                        "protected_branches": False,
                        "custom_branch_policies": True,
                    },
                    "id": 1001 if path == self.stage_policy else 1002,
                    "name": "maven-central-stage" if path == self.stage_policy else "maven-central-release",
                    "updated_at": "2026-07-17T07:55:00Z",
                    # This is the nested shape returned by GitHub's GET
                    # environment REST endpoint, not a made-up top-level
                    # prevent_self_review field.
                    "protection_rules": [
                        {
                            "id": 1,
                            "node_id": "MDQ6UmVxdWlyZWRSZXZpZXdlcnMx",
                            "type": "required_reviewers",
                            "prevent_self_review": False,
                            "reviewers": [
                                {
                                    "type": "User",
                                    "reviewer": {"id": 123456, "login": CP.APPROVED_ENVIRONMENT_REVIEWER},
                                }
                            ],
                        }
                    ],
                    }
                ),
                encoding="utf-8",
            )
        self.admin_bypass_attestation = self.root / "admin-bypass-attestation.json"
        self.admin_bypass_attestation.write_text(
            json.dumps(
                {
                    "format": CP.ADMIN_BYPASS_ATTESTATION_FORMAT,
                    "repository": REPOSITORY,
                    "source_kind": "user-export",
                    "complete": True,
                    "coverage_start": "2026-07-17T07:00:00Z",
                    "coverage_end": "2026-07-17T07:59:00Z",
                    "events": [
                        {
                            "action": "environment.update_protection_rule",
                            "created_at": "2026-07-17T07:56:00Z",
                            "repo": REPOSITORY,
                            "environment_name": environment,
                            "environment_id": environment_id,
                            "can_admins_bypass": False,
                        }
                        for environment, environment_id in (
                            ("maven-central-stage", 1001),
                            ("maven-central-release", 1002),
                        )
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.policy_audit = self.root / "policy-audit.json"
        CP.write_environment_policy_audit(
            self.stage_policy,
            self.stage_deployment_policies,
            self.release_policy,
            self.release_deployment_policies,
            REPOSITORY,
            self.admin_bypass_attestation,
            GATE_TIME,
            "v10.19.0-agp9.1",
            self.policy_audit,
        )
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

    def _prepare_stage(
        self,
        transport: MockTransport,
        *,
        allow_network: bool = True,
    ) -> tuple[dict[str, object], Path, Path]:
        stage_manifest = self.root / "stage-manifest.json"
        stage_prepared = self.root / "stage-prepared.json"
        client = CP.PortalClient(SECRET, transport=transport, sleep=lambda _: None)
        if not transport.downloads:
            with zipfile.ZipFile(self.bundle) as archive:
                transport.downloads = {name: archive.read(name) for name in archive.namelist()}
        prepared_result = CP.stage(
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
            validated_mirror_evidence=self.root / "validated-evidence",
            stage_prepared=stage_prepared,
            stage_manifest=stage_manifest,
            token_env="UNUSED",
            allow_network=allow_network,
            attempts=3,
            delay_seconds=0,
            client=client,
            drop_failed_deployment=True,
        )
        return dict(prepared_result), stage_prepared, stage_manifest

    def _stage(
        self,
        transport: MockTransport,
        *,
        allow_network: bool = True,
        consumer_runner: object | None = None,
    ) -> tuple[dict[str, object], Path]:
        prepared_result, stage_prepared, stage_manifest = self._prepare_stage(
            transport, allow_network=allow_network
        )
        with mock.patch.dict(
            os.environ, {"CENTRAL_PORTAL_BEARER_TOKEN": SECRET}, clear=False
        ):
            result = CP.finalize_stage(
                **BINDING,
                stage_prepared=stage_prepared,
                stage_prepared_sha256=str(prepared_result["stage_prepared_sha256"]),
                validated_consumer_command=self.consumer_command,
                validated_consumer_gradle_home=self.root / "validated-home",
                validated_consumer_evidence=self.root / "validated-evidence",
                stage_manifest=stage_manifest,
                consumer_runner=consumer_runner or self._consumer_runner,
            )
        return dict(result), stage_manifest

    @staticmethod
    def _consumer_runner(args: list[str], env: dict[str, str]) -> None:
        evidence = Path(args[args.index("--evidence-dir") + 1])
        repository = args[args.index("--repository-url") + 1]
        mode = args[args.index("--mode") + 1]
        gradle_home = Path(args[args.index("--gradle-user-home") + 1])
        if mode == "validated":
            expected_repository = (
                "https://central.sonatype.com/api/v1/publisher/deployment/"
                "deployment-123/download"
            )
            if repository != expected_repository:
                raise AssertionError("consumer did not receive the exact deployment repository")
            if env.get("CENTRAL_PORTAL_BEARER_TOKEN") != SECRET:
                raise AssertionError("validated consumer did not receive its repository credential")
            bearer_index = args.index("--bearer-env")
            if args[bearer_index + 1] != "CENTRAL_PORTAL_BEARER_TOKEN":
                raise AssertionError("validated consumer received the wrong bearer environment")
            if not gradle_home.is_dir() or any(gradle_home.iterdir()):
                raise AssertionError("validated consumer Gradle home was not initially empty")
        else:
            if SECRET in env.values() or "CENTRAL_PORTAL_BEARER_TOKEN" in env:
                raise AssertionError("Portal token crossed a public consumer boundary")
            if "--bearer-env" in args:
                raise AssertionError("public consumer received a credential argument")
        evidence.mkdir(parents=True, exist_ok=True)
        checksums = evidence / "SHA256SUMS"
        checksums.write_text("consumer PASS\n", encoding="utf-8")
        (evidence / "consumer-evidence.json").write_text(
            json.dumps(
                {
                    "format": CP.CONSUMER_EVIDENCE_FORMAT,
                    "mode": mode,
                    "repository_url_sha256": hashlib.sha256(repository.encode("utf-8")).hexdigest(),
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
        control_calls = [call for call in transport.calls if "/download/" not in call[1]]
        self.assertEqual(len(control_calls), 3)
        upload_url = transport.calls[0][1]
        self.assertEqual(urlparse(upload_url).path, "/api/v1/publisher/upload")
        self.assertEqual(parse_qs(urlparse(upload_url).query), {"name": ["v10.19.0-agp9.1"], "publishingType": ["USER_MANAGED"]})
        self.assertTrue(all("/status?id=deployment-123" in call[1] for call in control_calls[1:]))
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
        mirror_evidence = self.root / "validated-evidence" / "validated-deployment-mirror-evidence.json"
        self.assertEqual(
            manifest["validated_deployment_mirror_evidence_sha256"],
            CP.sha256_file(mirror_evidence),
        )
        mirror_text = mirror_evidence.read_text(encoding="utf-8")
        self.assertNotIn("deployment-123", mirror_text)
        self.assertNotIn("/api/v1/publisher/deployment/", mirror_text)
        self.assertTrue(
            (
                self.root
                / "validated-evidence"
                / "validated-deployment-mirror"
                / "io/github/leminity/realm/realm-android-library/10.19.0-agp9.1/realm-android-library-10.19.0-agp9.1.aar"
            ).is_file()
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
                validated_mirror_evidence=self.root / "blocked-evidence",
                stage_prepared=self.root / "blocked-stage-prepared.json",
                stage_manifest=stage_manifest,
                token_env="UNUSED",
                allow_network=False,
                attempts=1,
                delay_seconds=0,
                client=client,
            )
        self.assertEqual(transport.calls, [])
        self.assertNotIn(SECRET, str(raised.exception))

    def test_stage_rejects_a_corrupt_validated_download_before_consumer(self) -> None:
        transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
                CP.HttpResponse(204, b""),
            ]
        )
        with zipfile.ZipFile(self.bundle) as archive:
            transport.downloads = {name: archive.read(name) for name in archive.namelist()}
        first_path = sorted(transport.downloads)[0]
        transport.downloads[first_path] = b"corrupt"
        with self.assertRaisesRegex(CP.PortalError, "download differs"):
            self._stage(transport)
        self.assertEqual(transport.calls[-1][0], "DELETE")
        self.assertTrue((self.root / "stage-manifest.json.failed.json").is_file())

    def test_consumer_subprocess_environment_is_allowlisted_and_tokenless(self) -> None:
        original = {
            name: os.environ.get(name)
            for name in (
                "CENTRAL_PORTAL_BEARER_TOKEN",
                "UNUSED",
                "MAVEN_SIGNING_KEY",
                "GITHUB_TOKEN",
            )
        }
        os.environ.update(
            {
                "CENTRAL_PORTAL_BEARER_TOKEN": SECRET,
                "UNUSED": SECRET,
                "MAVEN_SIGNING_KEY": "private-signing-key",
                "GITHUB_TOKEN": "github-token",
            }
        )
        captured: dict[str, str] = {}

        def capture(args: list[str], env: dict[str, str]) -> None:
            captured.update(env)
            self._consumer_runner(args, env)

        try:
            CP._run_consumer(
                self.consumer_command,
                repository_url="https://repo.maven.apache.org/maven2",
                mode="central",
                token_env="UNUSED",
                gradle_user_home=self.root / "allowlisted-home",
                evidence=self.root / "allowlisted-evidence",
                runner=capture,
            )
        finally:
            for name, value in original.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.assertNotIn("CENTRAL_PORTAL_BEARER_TOKEN", captured)
        self.assertNotIn("UNUSED", captured)
        self.assertNotIn("MAVEN_SIGNING_KEY", captured)
        self.assertNotIn("GITHUB_TOKEN", captured)

    def test_validated_bearer_environment_cannot_overwrite_consumer_isolation(self) -> None:
        for name in ("HOME", "GRADLE_USER_HOME", "PATH", "CI", "MAVEN_SIGNING_KEY"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(CP.PortalError, "collides with consumer environment"):
                    CP._run_consumer(
                        self.consumer_command,
                        repository_url=(
                            "https://central.sonatype.com/api/v1/publisher/deployment/"
                            "deployment-123/download"
                        ),
                        mode="validated",
                        token_env=name,
                        gradle_user_home=self.root / f"collision-{name}",
                        evidence=self.root / f"collision-evidence-{name}",
                        bearer_token=SECRET,
                        runner=self._consumer_runner,
                    )

    def test_consumer_home_filesystem_errors_are_portal_errors(self) -> None:
        gradle_home = self.root / "not-a-gradle-home"
        gradle_home.write_text("not a directory", encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "consumer Gradle home is unavailable"):
            CP._run_consumer(
                self.consumer_command,
                repository_url="https://repo.maven.apache.org/maven2",
                mode="central",
                token_env="CENTRAL_PORTAL_BEARER_TOKEN",
                gradle_user_home=gradle_home,
                evidence=self.root / "filesystem-error-evidence",
                runner=self._consumer_runner,
            )

    def test_stage_finalizer_consumes_the_exact_validated_repository_with_bearer(self) -> None:
        transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        prepared, prepared_path, stage_manifest = self._prepare_stage(transport)
        old = os.environ.get("CENTRAL_PORTAL_BEARER_TOKEN")
        try:
            os.environ.pop("CENTRAL_PORTAL_BEARER_TOKEN", None)
            with self.assertRaisesRegex(CP.PortalError, "Portal credential is not configured"):
                CP.finalize_stage(
                    **BINDING,
                    stage_prepared=prepared_path,
                    stage_prepared_sha256=str(prepared["stage_prepared_sha256"]),
                    validated_consumer_command=self.consumer_command,
                    validated_consumer_gradle_home=self.root / "split-home",
                    validated_consumer_evidence=self.root / "validated-evidence",
                    stage_manifest=stage_manifest,
                    consumer_runner=self._consumer_runner,
                )
            os.environ["CENTRAL_PORTAL_BEARER_TOKEN"] = SECRET
            result = CP.finalize_stage(
                **BINDING,
                stage_prepared=prepared_path,
                stage_prepared_sha256=str(prepared["stage_prepared_sha256"]),
                validated_consumer_command=self.consumer_command,
                validated_consumer_gradle_home=self.root / "split-home",
                validated_consumer_evidence=self.root / "validated-evidence",
                stage_manifest=stage_manifest,
                consumer_runner=self._consumer_runner,
            )
        finally:
            if old is None:
                os.environ.pop("CENTRAL_PORTAL_BEARER_TOKEN", None)
            else:
                os.environ["CENTRAL_PORTAL_BEARER_TOKEN"] = old
        self.assertEqual(result["deployment_id"], "deployment-123")

    def test_tokenless_process_rejects_every_protected_alias_in_a_parent(self) -> None:
        inner = f"""
import importlib.util, pathlib, sys
path = pathlib.Path({str(ROOT / 'tools' / 'central-portal.py')!r})
spec = importlib.util.spec_from_file_location('central_portal_probe', path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
try:
    module._assert_tokenless_process()
except module.PortalError:
    raise SystemExit(23)
raise SystemExit(0)
"""
        outer = """
import os, subprocess, sys
child = os.environ.copy()
child.pop(sys.argv[2], None)
raise SystemExit(subprocess.run([sys.executable, '-c', sys.argv[1]], env=child).returncode)
"""
        environment = os.environ.copy()
        for name in CP._PROTECTED_PROCESS_ENV_NAMES:
            environment.pop(name, None)
        for name in sorted(CP._PROTECTED_PROCESS_ENV_NAMES):
            with self.subTest(name=name):
                environment[name] = "ancestor-probe-not-a-real-token"
                completed = subprocess.run(
                    [sys.executable, "-c", outer, inner, name],
                    env=environment,
                    check=False,
                )
                self.assertEqual(completed.returncode, 23)
                environment.pop(name)

    def test_tokenless_process_crosses_kernel_unreadable_ancestor_and_keeps_checking(self) -> None:
        proc = self.root / "proc"
        for pid, parent, environment in (
            (300, 200, b"PATH=/usr/bin\0"),
            (200, 100, b"CENTRAL_PORTAL_BEARER_TOKEN=unreadable\0"),
            (100, 1, b"PATH=/usr/bin\0"),
        ):
            process = proc / str(pid)
            process.mkdir(parents=True)
            (process / "status").write_text(f"Name:\tprobe\nUid:\t{os.getuid()}\t{os.getuid()}\n", encoding="utf-8")
            (process / "environ").write_bytes(environment)
            (process / "stat").write_text(f"{pid} (probe) S {parent} 0 0 0\n", encoding="utf-8")

        unreadable = proc / "200" / "environ"
        original_read_bytes = Path.read_bytes

        def read_bytes(path: Path) -> bytes:
            if path == unreadable:
                raise PermissionError(13, "Permission denied", str(path))
            return original_read_bytes(path)

        with mock.patch.object(Path, "read_bytes", read_bytes):
            CP._assert_tokenless_process_ancestry(proc, 300, os.getuid())
            (proc / "100" / "environ").write_bytes(b"MAVEN_SIGNING_PASSWORD=readable-grandparent\0")
            with self.assertRaisesRegex(CP.PortalError, "tokenless consumer ancestor"):
                CP._assert_tokenless_process_ancestry(proc, 300, os.getuid())

    def test_tokenless_process_fails_closed_for_non_permission_proc_error(self) -> None:
        proc = self.root / "proc"
        process = proc / "300"
        process.mkdir(parents=True)
        (process / "status").write_text(f"Name:\tprobe\nUid:\t{os.getuid()}\t{os.getuid()}\n", encoding="utf-8")
        (process / "environ").write_bytes(b"PATH=/usr/bin\0")
        (process / "stat").write_text("300 (probe) S 1 0 0 0\n", encoding="utf-8")

        original_read_bytes = Path.read_bytes

        def read_bytes(path: Path) -> bytes:
            if path == process / "environ":
                raise OSError(5, "I/O error", str(path))
            return original_read_bytes(path)

        with mock.patch.object(Path, "read_bytes", read_bytes):
            with self.assertRaisesRegex(CP.PortalError, "cannot verify tokenless"):
                CP._assert_tokenless_process_ancestry(proc, 300, os.getuid())

    def test_stage_finalizer_rejects_mutation_against_portal_origin_digest(self) -> None:
        transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        result, prepared_path, stage_manifest = self._prepare_stage(transport)
        mutated = json.loads(prepared_path.read_text(encoding="utf-8"))
        mutated["post_portal_mutation"] = True
        prepared_path.write_text(json.dumps(mutated), encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "prepared stage SHA-256 mismatch"):
            CP.finalize_stage(
                **BINDING,
                stage_prepared=prepared_path,
                stage_prepared_sha256=str(result["stage_prepared_sha256"]),
                validated_consumer_command=self.consumer_command,
                validated_consumer_gradle_home=self.root / "mutated-stage-home",
                validated_consumer_evidence=self.root / "validated-evidence",
                stage_manifest=stage_manifest,
                consumer_runner=self._consumer_runner,
            )

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

        consumer_env: dict[str, str] = {}

        def capture_consumer(args: list[str], env: dict[str, str]) -> None:
            consumer_args[:] = args
            consumer_env.update(env)
            self._consumer_runner(args, env)

        release_prepared = self.root / "central-release-prepared.json"
        portal_result = CP.release(
            **BINDING,
            stage_manifest=stage_manifest,
            stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
            token_env="UNUSED",
            allow_network=True,
            attempts=3,
            delay_seconds=0,
            client=release_client,
            release_prepared=release_prepared,
            release_evidence=self.root / "central-release-outcome.json",
        )
        result = CP.finalize_release(
            **BINDING,
            stage_manifest=stage_manifest,
            stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
            release_prepared=release_prepared,
            release_prepared_sha256=str(portal_result["release_prepared_sha256"]),
            published_consumer_command=self.consumer_command,
            published_consumer_gradle_home=self.root / "central-home",
            published_consumer_evidence=self.root / "central-evidence",
            consumer_runner=capture_consumer,
            release_evidence=self.root / "central-release-outcome.json",
        )
        self.assertEqual(result["deployment_id"], "deployment-123")
        self.assertEqual(result["state"], "PUBLISHED")
        self.assertTrue(result["publication_state_trace"])
        release_outcome = json.loads(
            (self.root / "central-release-outcome.json").read_text(encoding="utf-8")
        )
        self.assertEqual(release_outcome["result"], "PASS")
        self.assertEqual(
            release_outcome["deployment_id_sha256"],
            hashlib.sha256(b"deployment-123").hexdigest(),
        )
        self.assertNotIn("deployment-123", json.dumps(release_outcome))
        self.assertEqual(release_transport.calls[0][1], "https://central.sonatype.com/api/v1/publisher/status?id=deployment-123")
        self.assertEqual(release_transport.calls[1][1], "https://central.sonatype.com/api/v1/publisher/deployment/deployment-123")
        self.assertTrue(all("deployment-123" in call[1] for call in release_transport.calls))
        self.assertEqual(
            consumer_args[consumer_args.index("--expected-realm-android-library-sha256") + 1],
            hashlib.sha256(b"public-aar").hexdigest(),
        )
        self.assertNotIn("CENTRAL_PORTAL_BEARER_TOKEN", consumer_env)
        self.assertNotIn("UNUSED", consumer_env)

        rejected_transport = MockTransport([])
        with self.assertRaisesRegex(CP.PortalError, "SHA-256 mismatch"):
            CP.release(
                **BINDING,
                stage_manifest=stage_manifest,
                stage_manifest_sha256="0" * 64,
                token_env="UNUSED",
                allow_network=True,
                attempts=1,
                delay_seconds=0,
                client=CP.PortalClient(SECRET, transport=rejected_transport, sleep=lambda _: None),
                release_prepared=self.root / "central-release-rejected.json",
            )
        self.assertEqual(rejected_transport.calls, [])

    def test_release_finalizer_rejects_mutation_against_portal_origin_digest(self) -> None:
        stage_transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        stage_result, stage_manifest = self._stage(stage_transport)
        release_prepared = self.root / "mutated-release-prepared.json"
        portal_result = CP.release(
            **BINDING,
            stage_manifest=stage_manifest,
            stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
            token_env="UNUSED",
            allow_network=True,
            attempts=2,
            delay_seconds=0,
            client=CP.PortalClient(
                SECRET,
                transport=MockTransport(
                    [
                        CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
                        CP.HttpResponse(204, b""),
                        CP.HttpResponse(200, b'{"deploymentState":"PUBLISHED"}'),
                    ]
                ),
                sleep=lambda _: None,
            ),
            release_prepared=release_prepared,
        )
        mutated = json.loads(release_prepared.read_text(encoding="utf-8"))
        mutated["post_portal_mutation"] = True
        release_prepared.write_text(json.dumps(mutated), encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "prepared release SHA-256 mismatch"):
            CP.finalize_release(
                **BINDING,
                stage_manifest=stage_manifest,
                stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
                release_prepared=release_prepared,
                release_prepared_sha256=str(portal_result["release_prepared_sha256"]),
                published_consumer_command=self.consumer_command,
                published_consumer_gradle_home=self.root / "mutated-release-home",
                published_consumer_evidence=self.root / "mutated-release-evidence",
                consumer_runner=self._consumer_runner,
                release_evidence=self.root / "mutated-release-outcome.json",
            )

    def test_stale_stage_recovery_is_rejected_before_consumer_or_portal_calls(self) -> None:
        stage_transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-stale"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        prepared_result, prepared_path, stage_manifest = self._prepare_stage(stage_transport)
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        prepared["commit"] = STALE_COMMIT
        prepared["core_commit"] = STALE_CORE_COMMIT
        prepared["runtime_provenance"]["head"] = STALE_COMMIT
        prepared["runtime_provenance"]["core_commit"] = STALE_CORE_COMMIT
        prepared_path.write_text(json.dumps(prepared), encoding="utf-8")

        consumer_called = False

        def unexpected_consumer(_: list[str], __: dict[str, str]) -> None:
            nonlocal consumer_called
            consumer_called = True

        with self.assertRaisesRegex(CP.PortalError, "exact final source/tag/Core binding"):
            CP.finalize_stage(
                **FINAL_BINDING,
                stage_prepared=prepared_path,
                stage_prepared_sha256=CP.sha256_file(prepared_path),
                validated_consumer_command=self.consumer_command,
                validated_consumer_gradle_home=self.root / "stale-stage-home",
                validated_consumer_evidence=self.root / "validated-evidence",
                stage_manifest=stage_manifest,
                consumer_runner=unexpected_consumer,
            )
        self.assertFalse(consumer_called)
        self.assertFalse(stage_manifest.exists())

        stale_manifest = dict(prepared)
        stale_manifest["format"] = CP.STAGE_MANIFEST_FORMAT
        stale_manifest.pop("validated_mirror_url")
        stale_manifest["validated_consumer_evidence_sha256"] = "f" * 64
        stale_manifest_path = self.root / "stale-stage-manifest.json"
        stale_manifest_path.write_text(json.dumps(stale_manifest), encoding="utf-8")
        rejected_transport = MockTransport([])
        with self.assertRaisesRegex(CP.PortalError, "exact final source/tag/Core binding"):
            CP.release(
                **FINAL_BINDING,
                stage_manifest=stale_manifest_path,
                stage_manifest_sha256=CP.sha256_file(stale_manifest_path),
                token_env="UNUSED",
                allow_network=True,
                attempts=1,
                delay_seconds=0,
                client=CP.PortalClient(
                    SECRET, transport=rejected_transport, sleep=lambda _: None
                ),
                release_prepared=self.root / "stale-release-prepared.json",
            )
        self.assertEqual(rejected_transport.calls, [])

    def test_release_finalizer_rejects_a_self_hashed_wrong_final_deployment_trace(self) -> None:
        stage_transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        stage_result, stage_manifest = self._stage(stage_transport)
        release_prepared = self.root / "wrong-trace-release-prepared.json"
        CP.release(
            **BINDING,
            stage_manifest=stage_manifest,
            stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
            token_env="UNUSED",
            allow_network=True,
            attempts=2,
            delay_seconds=0,
            client=CP.PortalClient(
                SECRET,
                transport=MockTransport(
                    [
                        CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
                        CP.HttpResponse(204, b""),
                        CP.HttpResponse(200, b'{"deploymentState":"PUBLISHED"}'),
                    ]
                ),
                sleep=lambda _: None,
            ),
            release_prepared=release_prepared,
        )
        mutated = json.loads(release_prepared.read_text(encoding="utf-8"))
        mutated["publication_state_trace"][-1]["deployment_id"] = "deployment-456"
        release_prepared.write_text(json.dumps(mutated), encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "exact final PUBLISHED deployment trace"):
            CP.finalize_release(
                **BINDING,
                stage_manifest=stage_manifest,
                stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
                release_prepared=release_prepared,
                release_prepared_sha256=CP.sha256_file(release_prepared),
                published_consumer_command=self.consumer_command,
                published_consumer_gradle_home=self.root / "wrong-trace-home",
                published_consumer_evidence=self.root / "wrong-trace-evidence",
                consumer_runner=self._consumer_runner,
                release_evidence=self.root / "wrong-trace-outcome.json",
            )

    def test_release_rejects_out_of_band_published_state(self) -> None:
        stage_transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        stage_result, stage_manifest = self._stage(stage_transport)
        release_transport = MockTransport([CP.HttpResponse(200, b'{"deploymentState":"PUBLISHED"}')])
        with self.assertRaisesRegex(CP.PortalError, "outside the approved release transaction"):
            CP.release(
                **BINDING,
                stage_manifest=stage_manifest,
                stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
                token_env="UNUSED",
                allow_network=True,
                attempts=2,
                delay_seconds=0,
                client=CP.PortalClient(SECRET, transport=release_transport, sleep=lambda _: None),
                release_prepared=self.root / "resume-release-prepared.json",
            )
        self.assertEqual(len(release_transport.calls), 1)
        self.assertIn("/status?id=deployment-123", release_transport.calls[0][1])

    def test_release_poll_tolerates_async_validated_then_publishing(self) -> None:
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
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
                CP.HttpResponse(200, b'{"deploymentState":"PUBLISHING"}'),
                CP.HttpResponse(200, b'{"deploymentState":"PUBLISHED"}'),
            ]
        )
        release_prepared = self.root / "async-release-prepared.json"
        result = CP.release(
            **BINDING,
            stage_manifest=stage_manifest,
            stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
            token_env="UNUSED",
            allow_network=True,
            attempts=3,
            delay_seconds=0,
            client=CP.PortalClient(SECRET, transport=release_transport, sleep=lambda _: None),
            release_prepared=release_prepared,
        )
        self.assertEqual(result["state"], "PUBLISHED")
        self.assertEqual([item["state"] for item in result["publication_state_trace"][-3:]], ["VALIDATED", "PUBLISHING", "PUBLISHED"])

    def test_release_failure_writes_redacted_durable_outcome(self) -> None:
        stage_transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        stage_result, stage_manifest = self._stage(stage_transport)
        evidence = self.root / "failed-release-evidence.json"
        release_transport = MockTransport(
            [
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
                CP.HttpResponse(204, b""),
                CP.HttpResponse(200, b'{"deploymentState":"FAILED"}'),
            ]
        )
        with self.assertRaises(CP.PortalError):
            CP.release(
                **BINDING,
                stage_manifest=stage_manifest,
                stage_manifest_sha256=str(stage_result["stage_manifest_sha256"]),
                token_env="UNUSED",
                allow_network=True,
                attempts=2,
                delay_seconds=0,
                client=CP.PortalClient(SECRET, transport=release_transport, sleep=lambda _: None),
                release_prepared=self.root / "failed-release-prepared.json",
                release_evidence=evidence,
            )
        outcome = json.loads(evidence.read_text(encoding="utf-8"))
        self.assertEqual(outcome["result"], "FAILED")
        self.assertEqual(
            outcome["deployment_id_sha256"],
            hashlib.sha256(b"deployment-123").hexdigest(),
        )
        self.assertTrue(outcome["publication_state_trace"])
        self.assertNotIn("deployment-123", evidence.read_text(encoding="utf-8"))
        self.assertNotIn(SECRET, evidence.read_text(encoding="utf-8"))

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
                "--validated-mirror-evidence",
                str(self.root / "cli-stage-evidence"),
                "--stage-prepared",
                str(self.root / "cli-stage-prepared.json"),
                "--stage-manifest",
                str(self.root / "cli-stage-manifest.json"),
                "--drop-failed-deployment",
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

    def test_release_cli_parses_portal_only_arguments_and_fails_closed_without_network(self) -> None:
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
                *BINDING_ARGS,
                "--stage-manifest",
                str(stage_manifest),
                "--stage-manifest-sha256",
                str(stage_result["stage_manifest_sha256"]),
                "--release-prepared",
                str(self.root / "cli-release-prepared.json"),
                "--release-evidence",
                str(self.root / "cli-release-outcome.json"),
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

    def test_verify_stage_manifest_cli_writes_only_a_sanitized_result_projection(self) -> None:
        stage_transport = MockTransport(
            [
                CP.HttpResponse(201, b"deployment-123"),
                CP.HttpResponse(200, b'{"deploymentState":"VALIDATED"}'),
            ]
        )
        stage_result, stage_manifest = self._stage(stage_transport)
        result_file = self.root / "verify-stage-result.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "central-portal.py"),
                "verify-stage-manifest",
                *BINDING_ARGS,
                "--stage-manifest",
                str(stage_manifest),
                "--stage-manifest-sha256",
                str(stage_result["stage_manifest_sha256"]),
                "--result-file",
                str(result_file),
            ],
            check=False,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        expected = {
            "stage_manifest_sha256": stage_result["stage_manifest_sha256"],
            "status": "VERIFIED",
        }
        self.assertEqual(json.loads(completed.stdout), expected)
        self.assertEqual(json.loads(result_file.read_text(encoding="utf-8")), expected)
        for sensitive in (
            "deployment-123",
            "/api/v1/publisher/deployment/",
            "deployment_id",
            "deployment_repository",
        ):
            self.assertNotIn(sensitive, completed.stdout)
            self.assertNotIn(sensitive, result_file.read_text(encoding="utf-8"))

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
        self.assertIn('"drop_policy":"drop-after-evidence"', first)
        self.assertIn('"state_trace":[', first)
        self.assertNotIn("deployment-123", first)
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
            drop_failed_deployment=True,
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

        def fail_consumer(_: list[str], __: dict[str, str]) -> None:
            raise CP.PortalError("consumer gate failed")

        with self.assertRaisesRegex(CP.PortalError, "consumer gate failed"):
            self._stage(transport, consumer_runner=fail_consumer)
        failure_path = self.root / "stage-manifest.json.failed.json"
        evidence = json.loads(failure_path.read_text(encoding="utf-8"))
        self.assertEqual(
            evidence["deployment_id_sha256"],
            hashlib.sha256(b"deployment-123").hexdigest(),
        )
        self.assertNotIn("deployment-123", json.dumps(evidence))
        self.assertEqual(evidence["expected_state"], "CONSUMER_PASS")
        self.assertEqual(evidence["drop_policy"], "retain-for-support-or-manual-recovery")
        self.assertFalse(any(call[0] == "DELETE" for call in transport.calls))
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

    def test_retry_after_cannot_exceed_remaining_poll_deadline(self) -> None:
        delays: list[float] = []
        transport = MockTransport(
            [CP.HttpResponse(200, b'{"deploymentState":"PENDING"}', {"Retry-After": "7"})]
        )
        client = CP.PortalClient(
            SECRET,
            transport=transport,
            sleep=delays.append,
            clock=lambda: 100.0,
        )
        with self.assertRaisesRegex(CP.PortalError, "bounded polling deadline"):
            client.poll(
                "deployment-123",
                "VALIDATED",
                attempts=2,
                delay_seconds=1,
                deadline_seconds=5,
            )
        self.assertEqual(delays, [])

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

    def test_policy_audit_is_redacted_hashed_and_requires_exact_solo_reviewer(self) -> None:
        audit_sha = CP.verify_environment_policy_audit(self.policy_audit)
        self.assertEqual(audit_sha, CP.sha256_file(self.policy_audit))
        audit = self.policy_audit.read_text(encoding="utf-8")
        self.assertNotIn(CP.APPROVED_ENVIRONMENT_REVIEWER, audit)
        expected_fingerprint = hashlib.sha256(CP.APPROVED_ENVIRONMENT_REVIEWER.encode("utf-8")).hexdigest()
        audit_value = json.loads(audit)
        for environment in ("stage", "release"):
            self.assertIs(audit_value[environment]["prevent_self_review"], False)
            self.assertEqual(audit_value[environment]["reviewer_fingerprints"], [expected_fingerprint])

        def write_tampered_audit(name: str, value: dict[str, object]) -> Path:
            unsigned = {key: item for key, item in value.items() if key != "audit_sha256"}
            value["audit_sha256"] = hashlib.sha256(
                json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            path = self.root / name
            path.write_text(json.dumps(value), encoding="utf-8")
            return path

        tampered_self_review = json.loads(audit)
        tampered_self_review["stage"]["prevent_self_review"] = True
        tampered_self_review_path = write_tampered_audit(
            "tampered-self-review-audit.json", tampered_self_review
        )
        with self.assertRaisesRegex(CP.PortalError, "does not enable solo reviewer self-review"):
            CP.verify_environment_policy_audit(tampered_self_review_path)

        tampered_reviewer = json.loads(audit)
        tampered_reviewer["release"]["reviewer_fingerprints"] = ["0" * 64]
        tampered_reviewer_path = write_tampered_audit(
            "tampered-reviewer-audit.json", tampered_reviewer
        )
        with self.assertRaisesRegex(CP.PortalError, "exact solo reviewer"):
            CP.verify_environment_policy_audit(tampered_reviewer_path)

        wrong_reviewer = self.root / "wrong-reviewer-policy.json"
        wrong_policy = json.loads(self.stage_policy.read_text(encoding="utf-8"))
        wrong_policy["protection_rules"][0]["reviewers"][0]["reviewer"]["login"] = "OtherUser"
        wrong_reviewer.write_text(json.dumps(wrong_policy), encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "exactly Leminity"):
            CP.write_environment_policy_audit(
                wrong_reviewer,
                self.stage_deployment_policies,
                self.release_policy,
                self.release_deployment_policies,
                REPOSITORY,
                self.admin_bypass_attestation,
                GATE_TIME,
                "v10.19.0-agp9.1",
                self.root / "wrong-reviewer-audit.json",
            )

        multiple_reviewers = self.root / "multiple-reviewers-policy.json"
        multiple_policy = json.loads(self.stage_policy.read_text(encoding="utf-8"))
        multiple_policy["protection_rules"][0]["reviewers"].append(
            {"type": "User", "reviewer": {"id": 654321, "login": "OtherUser"}}
        )
        multiple_reviewers.write_text(json.dumps(multiple_policy), encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "exactly Leminity"):
            CP.write_environment_policy_audit(
                multiple_reviewers,
                self.stage_deployment_policies,
                self.release_policy,
                self.release_deployment_policies,
                REPOSITORY,
                self.admin_bypass_attestation,
                GATE_TIME,
                "v10.19.0-agp9.1",
                self.root / "multiple-reviewers-audit.json",
            )

        policy = json.loads(self.stage_policy.read_text(encoding="utf-8"))
        policy["protection_rules"][0]["prevent_self_review"] = True
        prevented_self_review = self.root / "prevented-self-review.json"
        prevented_self_review.write_text(json.dumps(policy), encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "self-review must be enabled"):
            CP.write_environment_policy_audit(
                prevented_self_review,
                self.stage_deployment_policies,
                self.release_policy,
                self.release_deployment_policies,
                REPOSITORY,
                self.admin_bypass_attestation,
                GATE_TIME,
                "v10.19.0-agp9.1",
                self.root / "prevented-self-review-audit.json",
            )
        broad = self.root / "broad-deployment-policies.json"
        broad.write_text(
            json.dumps(
                {
                    "total_count": 2,
                    "branch_policies": [
                        {"id": 1, "name": CP.APPROVED_DEPLOYMENT_TAG_PATTERN, "type": "tag"},
                        {"id": 2, "name": "*", "type": "tag"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CP.PortalError, "custom tag policy"):
            CP.write_environment_policy_audit(
                self.stage_policy,
                broad,
                self.release_policy,
                self.release_deployment_policies,
                REPOSITORY,
                self.admin_bypass_attestation,
                GATE_TIME,
                "v10.19.0-agp9.1",
                self.root / "broad-policy-audit.json",
            )

        branch_policy = self.root / "branch-deployment-policy.json"
        branch_policy.write_text(
            json.dumps(
                {
                    "total_count": 1,
                    "branch_policies": [
                        {"id": 1, "name": CP.APPROVED_DEPLOYMENT_TAG_PATTERN, "type": "branch"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CP.PortalError, "custom tag policy"):
            CP.write_environment_policy_audit(
                self.stage_policy,
                branch_policy,
                self.release_policy,
                self.release_deployment_policies,
                REPOSITORY,
                self.admin_bypass_attestation,
                GATE_TIME,
                "v10.19.0-agp9.1",
                self.root / "branch-policy-audit.json",
            )

    def test_policy_audit_fails_closed_for_missing_true_or_stale_admin_bypass_proof(self) -> None:
        def audit(attestation: Path | None, output: str) -> None:
            CP.write_environment_policy_audit(
                self.stage_policy,
                self.stage_deployment_policies,
                self.release_policy,
                self.release_deployment_policies,
                REPOSITORY,
                attestation,
                GATE_TIME,
                "v10.19.0-agp9.1",
                self.root / output,
            )

        with self.assertRaisesRegex(CP.PortalError, "bypass state is unproven"):
            audit(None, "missing-bypass-audit.json")

        enabled = json.loads(self.stage_policy.read_text(encoding="utf-8"))
        enabled["can_admins_bypass"] = True
        enabled_path = self.root / "enabled-admin-bypass.json"
        enabled_path.write_text(json.dumps(enabled), encoding="utf-8")
        original_stage = self.stage_policy
        self.stage_policy = enabled_path
        try:
            with self.assertRaisesRegex(CP.PortalError, "bypass is enabled"):
                audit(self.admin_bypass_attestation, "enabled-bypass-audit.json")
        finally:
            self.stage_policy = original_stage

        stale = json.loads(self.admin_bypass_attestation.read_text(encoding="utf-8"))
        stale["coverage_end"] = "2026-07-17T07:00:00Z"
        stale_path = self.root / "stale-admin-bypass.json"
        stale_path.write_text(json.dumps(stale), encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "log (coverage is stale|does not cover the live policy)"):
            audit(stale_path, "stale-bypass-audit.json")

        ambiguous = json.loads(self.admin_bypass_attestation.read_text(encoding="utf-8"))
        ambiguous["events"][0]["can_admins_bypass"] = "false"
        ambiguous_path = self.root / "ambiguous-admin-bypass.json"
        ambiguous_path.write_text(json.dumps(ambiguous), encoding="utf-8")
        with self.assertRaisesRegex(CP.PortalError, "event is ambiguous"):
            audit(ambiguous_path, "ambiguous-bypass-audit.json")

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
        self.assertEqual(
            workflow.count("G011_ENVIRONMENT_POLICY_TOKEN: ${{ secrets.G011_ENVIRONMENT_POLICY_TOKEN }}"),
            2,
        )
        self.assertEqual(
            workflow.count(
                "G011_ENVIRONMENT_BYPASS_ATTESTATION: ${{ secrets.G011_ENVIRONMENT_BYPASS_ATTESTATION }}"
            ),
            2,
        )
        self.assertEqual(workflow.count("--admin-bypass-attestation"), 2)
        self.assertEqual(workflow.count("--gate-time"), 2)
        self.assertIn("audit-environment-policy", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("group: realm-central-${{ github.event.release.tag_name }}", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("if: ${{ always() && steps.stage_recovery.outputs.recovered != 'true' }}", workflow)
        self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", workflow)
        self.assertIn("g011-central-stage-outcome-${{ steps.source.outputs.commit }}", workflow)
        self.assertIn("Recover a prior immutable stage outcome without re-uploading", workflow)
        self.assertIn("multiple prior stage outcomes exist for the exact release commit", workflow)
        self.assertIn("prior immutable failed/ambiguous stage outcome forbids automatic re-upload", workflow)
        self.assertIn("tools/central-portal.py verify-stage-manifest", workflow)
        self.assertGreaterEqual(workflow.count("split('@', 1)[0]"), 2)
        self.assertIn("maven-central-stage-manifest.json.failed.json", workflow)
        self.assertIn("/deployment-branch-policies?per_page=100", workflow)
        self.assertIn("--stage-deployment-policies", workflow)
        self.assertIn("--release-deployment-policies", workflow)
        self.assertIn("--release-tag \"$TAG\"", workflow)
        self.assertIn("Reaudit protected environments immediately before publication", workflow)
        self.assertIn("maven-central-release-environment-policy-audit.json", workflow)
        self.assertIn("maven-central-release-evidence.json", workflow)
        self.assertIn("g011-central-release-intent-${{ needs.stage.outputs.source_commit }}", workflow)
        self.assertIn("g011-central-release-outcome-${{ needs.stage.outputs.source_commit }}", workflow)
        self.assertIn("g011-central-release-diagnostic-${{ github.run_id }}-${{ github.run_attempt }}", workflow)
        self.assertIn("prior publication intent or outcome forbids same-version retry", workflow)
        self.assertIn("realm-maven-central-publication-intent-v1", workflow)
        self.assertIn("stage evidence secret scan PASS", workflow)
        self.assertIn("release evidence secret scan PASS", workflow)
        self.assertIn("g011-central-stage-intent-${{ steps.source.outputs.commit }}", workflow)
        self.assertIn("g011-central-stage-diagnostic-${{ github.run_id }}-${{ github.run_attempt }}", workflow)
        self.assertIn("steps.stage_transaction.outputs.transaction == 'true'", workflow)
        self.assertIn("Portal stage entered without exactly one durable outcome", workflow)
        self.assertIn("prior pre-upload intent has no immutable outcome", workflow)
        self.assertNotIn("head_branch", workflow)
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
        self.assertEqual(workflow.count('= "$expected_archive_sha"'), 3)
        self.assertIn('test "$stage_tag" = "$TAG"', release_job)
        self.assertIn('test "$stage_version" = "$(cat version.txt)"', release_job)
        self.assertIn('mapfile -t version_lines < version.txt', workflow)
        self.assertIn('test "${#version_lines[@]}" = 1', workflow)
        self.assertIn("--validated-consumer-command", workflow)
        self.assertIn("--validated-consumer-bearer-env CENTRAL_PORTAL_BEARER_TOKEN", workflow)
        self.assertIn('--bearer-env) bearer_env="$2"', workflow)
        self.assertIn('--mode validated --bearer-env "$bearer_env"', workflow)
        self.assertNotIn("validated mirror consumer rejects credentials", workflow)
        self.assertIn("supplementary validated mirror is missing", workflow)
        self.assertIn("--published-consumer-command", workflow)
        self.assertIn("Upload one USER_MANAGED deployment and directly validate its exact repository", workflow)
        self.assertNotIn("Consume the validated mirror in a separate tokenless process", workflow)
        self.assertIn("Publish the exact staged deployment in a Portal-only process", workflow)
        self.assertIn("Consume Maven Central in a separate tokenless process", workflow)
        self.assertEqual(workflow.count("--result-file"), 4)
        self.assertNotIn("| tee", workflow)
        self.assertIn("tools/central-portal.py finalize-stage", workflow)
        self.assertIn("tools/central-portal.py finalize-release", workflow)
        self.assertIn("stage_prepared_sha256=%s", workflow)
        self.assertIn("release_prepared_sha256=%s", workflow)
        self.assertIn('--stage-prepared-sha256 "$stage_prepared_sha256"', workflow)
        self.assertNotIn("${{ steps.portal_stage.outputs.stage_prepared_sha256 }}", workflow)
        self.assertIn("${{ steps.portal_release.outputs.release_prepared_sha256 }}", workflow)
        self.assertNotIn('prepared_sha="$(sha256sum "$prepared"', workflow)
        self.assertLess(workflow.index("tools/central-portal.py stage"), workflow.index("tools/central-portal.py finalize-stage"))
        self.assertLess(release_job.index("tools/central-portal.py release"), release_job.index("tools/central-portal.py finalize-release"))
        self.assertEqual(workflow.count("CENTRAL_PORTAL_BEARER_TOKEN: ${{ secrets.CENTRAL_PORTAL_BEARER_TOKEN }}"), 2)
        self.assertEqual(workflow.count("protected credential variable reached tokenless"), 1)
        self.assertGreaterEqual(workflow.count("mktemp -d \"$RUNNER_TEMP/maven-central-"), 2)
        self.assertGreaterEqual(workflow.count("trap 'rm -rf \"$policy_dir\"' EXIT"), 2)
        self.assertGreaterEqual(workflow.count("chmod 600 \"$policy_dir/admin-bypass-attestation.json\""), 2)
        self.assertIn("G011_OFFICIAL_GRADLE_HOME_ARCHIVE", workflow)
        self.assertIn("G011_OFFICIAL_GRADLE_HOME_ARCHIVE_SHA256", workflow)
        self.assertEqual(workflow.count("--official-inputs-preflight-only"), 2)
        self.assertLess(
            workflow.index("Preflight persistent official inputs before Portal upload"),
            workflow.index("tools/central-portal.py stage"),
        )
        self.assertLess(
            release_job.index("Preflight persistent official inputs before Central publication"),
            release_job.index("tools/central-portal.py release"),
        )
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
        self.assertIn("g011-gradle-signing-${{ github.run_id }}-${{ github.run_attempt }}", workflow)
        self.assertIn("signing Gradle home secret scan PASS", workflow)
        self.assertIn('rm -rf "$RUNNER_TEMP/g011-gradle-validated"', workflow)
        self.assertIn('rm -rf "$RUNNER_TEMP/g011-gradle-central"', workflow)
        self.assertIn("curl --config -", workflow)
        self.assertNotIn(".github-curl.conf", workflow)
        self.assertNotIn('--header "Authorization: Bearer $', workflow)
        self.assertNotIn('"$GH_TOKEN" "$root/selection.json"', workflow)
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
        self.assertNotIn("> SHA256SUMS.tmp", workflow)
        self.assertEqual(workflow.count("manifest_tmp=.SHA256SUMS.tmp"), 2)
        self.assertEqual(workflow.count("verify_tmp=.checksum-verify.tmp"), 2)
        self.assertEqual(workflow.count("! -name .SHA256SUMS.tmp ! -name .checksum-verify.tmp"), 2)
        self.assertEqual(workflow.count('> "$manifest_tmp"'), 2)
        self.assertGreaterEqual(workflow.count("sha256sum -c SHA256SUMS"), 2)
        legacy = (ROOT / "tools" / "release.sh").read_text(encoding="utf-8")
        self.assertIn("Protected Maven Central release GitHub workflow", legacy)
        self.assertNotIn("mavenCentralUpload", legacy)
        publish_helper = (ROOT / "tools" / "publish_release.sh").read_text(encoding="utf-8")
        self.assertIn('gradlew" --no-daemon "$task"', publish_helper)
        portal_helper = (ROOT / "tools" / "central-portal.py").read_text(encoding="utf-8")
        self.assertIn("env=dict(env)", portal_helper)
        self.assertIn("validated-deployment-mirror", portal_helper)
        self.assertIn("bounded polling deadline", portal_helper)


if __name__ == "__main__":
    unittest.main()
