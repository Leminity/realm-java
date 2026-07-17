#!/usr/bin/env python3
"""Minimal, explicit Maven Central Portal stage/release client.

The command has no ambient network behavior.  The only two commands that can
contact the Portal (``stage`` and ``release``) require ``--allow-network``.
They deliberately model the Portal's two-step USER_MANAGED deployment flow:
staging can upload and wait for VALIDATED, while release can publish only the
deployment named by an immutable, hashed stage manifest.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import uuid
import zipfile


PORTAL_URL = "https://central.sonatype.com"
TAG_RE = re.compile(r"^v10\.19\.0-agp9\.[1-9][0-9]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
STAGE_MANIFEST_FORMAT = "realm-maven-central-stage-v2"
POLICY_AUDIT_FORMAT = "realm-maven-central-environment-policy-audit-v1"
CONSUMER_EVIDENCE_FORMAT = "realm-maven-central-consumer-evidence-v1"


class PortalError(RuntimeError):
    """A safe, non-secret-bearing operational error."""


class DeploymentFailed(PortalError):
    """A non-secret status failure that can be preserved as local evidence."""

    def __init__(self, deployment_id: str, expected: str, state: str) -> None:
        super().__init__(f"deployment did not reach expected {expected} state")
        self.deployment_id = deployment_id
        self.expected = expected
        self.state = state


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[str, str, Mapping[str, str], bytes | None], HttpResponse]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise PortalError(f"invalid {field}")
    return value


def _require_git_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not GIT_SHA_RE.fullmatch(value):
        raise PortalError(f"invalid {field}")
    return value


def validate_release_binding(tag: str, version: str, commit: str, core_commit: str) -> None:
    """Validate values that identify the immutable source state.

    Git resolves the tag, verifies the checked-out commit, submodule gitlink,
    and clean tree in the workflow.  This function makes the handoff manifest
    reject malformed or substituted values as well.
    """

    if not TAG_RE.fullmatch(tag):
        raise PortalError("tag is outside the approved release family")
    if tag[1:] != version:
        raise PortalError("tag/version mismatch")
    _require_git_sha(commit, "commit")
    _require_git_sha(core_commit, "core_commit")


def _safe_manifest_paths(source_manifest: Mapping[str, object]) -> dict[str, str]:
    if source_manifest.get("format") != "g008-local-maven-central-inputs-v1":
        raise PortalError("unexpected source manifest format")
    entries = source_manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise PortalError("source manifest has no files")

    expected: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise PortalError("invalid source manifest entry")
        path = entry.get("path")
        if not isinstance(path, str) or not path or path.startswith("/"):
            raise PortalError("invalid source manifest path")
        parts = path.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise PortalError("invalid source manifest path")
        if path in expected:
            raise PortalError("duplicate source manifest path")
        expected[path] = _require_sha256(entry.get("sha256"), "source manifest file sha256")
    return expected


def verify_bundle_binding(bundle: Path, source_manifest: Path) -> tuple[str, str]:
    """Prove the exact Central bundle is the file set in the source manifest."""

    if not bundle.is_file():
        raise PortalError("bundle does not exist")
    if not source_manifest.is_file():
        raise PortalError("source manifest does not exist")
    try:
        manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortalError("source manifest is unreadable") from error
    if not isinstance(manifest, dict):
        raise PortalError("source manifest is not an object")
    expected = _safe_manifest_paths(manifest)
    try:
        with zipfile.ZipFile(bundle) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise PortalError("bundle contains duplicate paths")
            if set(names) != set(expected):
                raise PortalError("bundle/source manifest paths differ")
            for name in names:
                if hashlib.sha256(archive.read(name)).hexdigest() != expected[name]:
                    raise PortalError("bundle/source manifest digest differs")
    except zipfile.BadZipFile as error:
        raise PortalError("bundle is not a valid ZIP") from error
    return sha256_file(bundle), sha256_file(source_manifest)


def realm_android_library_aar_sha256(bundle: Path, version: str) -> str:
    """Return the exact public Android AAR digest carried by a verified bundle.

    The release job cannot inspect a build-directory bundle that existed only
    in the staging job.  Binding this public AAR digest lets it freshly
    download the exact Central coordinate and verify it before ELF inspection.
    """

    relative_path = (
        "io/github/leminity/realm/realm-android-library/"
        f"{version}/realm-android-library-{version}.aar"
    )
    try:
        with zipfile.ZipFile(bundle) as archive:
            try:
                contents = archive.read(relative_path)
            except KeyError as error:
                raise PortalError("bundle lacks the exact realm-android-library AAR") from error
    except zipfile.BadZipFile as error:
        raise PortalError("bundle is not a valid ZIP") from error
    return hashlib.sha256(contents).hexdigest()


def _read_json_object(path: Path, description: str) -> Mapping[str, object]:
    if not path.is_file():
        raise PortalError(f"{description} does not exist")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortalError(f"{description} is unreadable") from error
    if not isinstance(value, dict):
        raise PortalError(f"{description} is not an object")
    return value


def _first_string(value: Mapping[str, object], *names: str) -> str | None:
    for name in names:
        candidate = value.get(name)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def verify_runtime_provenance(path: Path, commit: str, core_commit: str) -> Mapping[str, str]:
    """Reject a runtime handoff that is not bound to this exact source state.

    Task29 owns the producer. This deliberately accepts the producer's
    explicit ``head``/``commit`` spelling while requiring all four facts the
    release handoff needs: root HEAD, Core gitlink, WSL runtime evidence and
    independently checksummed CI evidence. A baseline-only manifest is not
    sufficient for a tag release.
    """

    provenance = _read_json_object(path, "runtime provenance")
    source = provenance.get("source")
    wsl = provenance.get("wsl")
    ci = provenance.get("ci")
    if not isinstance(source, dict) or not isinstance(wsl, dict) or not isinstance(ci, dict):
        raise PortalError("runtime provenance is incomplete")
    head = _first_string(source, "head", "commit", "root_commit")
    bound_core = _first_string(source, "core_gitlink", "core_commit")
    wsl_sha256 = _first_string(wsl, "runtime_sha256", "evidence_sha256")
    ci_sha256 = _first_string(ci, "evidence_sha256", "manifest_sha256")
    if head != commit or bound_core != core_commit:
        raise PortalError("runtime provenance source binding differs from release source")
    return {
        "sha256": sha256_file(path),
        "head": _require_git_sha(head, "runtime provenance head"),
        "core_commit": _require_git_sha(bound_core, "runtime provenance core commit"),
        "wsl_evidence_sha256": _require_sha256(wsl_sha256, "runtime provenance WSL evidence SHA-256"),
        "ci_evidence_sha256": _require_sha256(ci_sha256, "runtime provenance CI evidence SHA-256"),
    }


def _reviewer_fingerprints(policy: Mapping[str, object], environment: str) -> set[str]:
    rules = policy.get("protection_rules")
    if not isinstance(rules, list):
        raise PortalError(f"{environment}: required reviewers are not configured")
    reviewers: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "required_reviewers":
            continue
        configured = rule.get("reviewers")
        if not isinstance(configured, list):
            continue
        for reviewer in configured:
            if not isinstance(reviewer, dict):
                continue
            # GitHub's environment API has used both a direct reviewer shape
            # and ``{type, reviewer: {...}}``; numeric IDs are valid too.
            nested = reviewer.get("reviewer")
            candidate = nested if isinstance(nested, dict) else reviewer
            raw_identity = candidate.get("id") or candidate.get("node_id") or candidate.get("login")
            identity = str(raw_identity) if raw_identity is not None else None
            if identity:
                reviewers.add(hashlib.sha256(identity.encode("utf-8")).hexdigest())
    if not reviewers:
        raise PortalError(f"{environment}: required reviewers are not configured")
    return reviewers


def _environment_policy_summary(policy: Mapping[str, object], environment: str) -> Mapping[str, object]:
    reviewers = _reviewer_fingerprints(policy, environment)
    branch_policy = policy.get("deployment_branch_policy")
    if not isinstance(branch_policy, dict) or not (
        branch_policy.get("protected_branches") or branch_policy.get("custom_branch_policies")
    ):
        raise PortalError(f"{environment}: protected/custom tag policy is not configured")
    # GitHub's GET environment response places this setting on the
    # ``required_reviewers`` protection-rule object, not on the environment
    # object. Treat every other shape as unproven.
    rules = policy.get("protection_rules")
    has_prevent_self_review = isinstance(rules, list) and any(
        isinstance(rule, dict)
        and rule.get("type") == "required_reviewers"
        and rule.get("prevent_self_review") is True
        for rule in rules
    )
    if not has_prevent_self_review:
        raise PortalError(f"{environment}: prevent-self-review is not enabled")
    return {
        "environment": environment,
        # Fingerprints retain the independent-reviewer proof without exposing
        # account names in a durable release artifact.
        "reviewer_fingerprints": sorted(reviewers),
        "prevent_self_review": True,
        "protected_or_custom_tag_policy": True,
    }


def write_environment_policy_audit(stage_policy: Path, release_policy: Path, audit_file: Path) -> str:
    """Create a redacted, self-hashed proof of the server-side environment rules."""

    stage = _environment_policy_summary(_read_json_object(stage_policy, "stage environment policy"), "maven-central-stage")
    release = _environment_policy_summary(_read_json_object(release_policy, "release environment policy"), "maven-central-release")
    if set(stage["reviewer_fingerprints"]) & set(release["reviewer_fingerprints"]):
        raise PortalError("stage and release required reviewers are not distinct")
    payload: dict[str, object] = {"format": POLICY_AUDIT_FORMAT, "stage": stage, "release": release}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["audit_sha256"] = hashlib.sha256(canonical).hexdigest()
    _write_json(audit_file, payload)
    return sha256_file(audit_file)


def verify_environment_policy_audit(path: Path) -> str:
    audit = _read_json_object(path, "environment policy audit")
    if audit.get("format") != POLICY_AUDIT_FORMAT:
        raise PortalError("invalid environment policy audit format")
    stage = audit.get("stage")
    release = audit.get("release")
    if not isinstance(stage, dict) or not isinstance(release, dict):
        raise PortalError("environment policy audit is incomplete")
    for policy, environment in ((stage, "maven-central-stage"), (release, "maven-central-release")):
        if policy.get("environment") != environment or policy.get("prevent_self_review") is not True:
            raise PortalError("environment policy audit lacks prevent-self-review")
        if policy.get("protected_or_custom_tag_policy") is not True:
            raise PortalError("environment policy audit lacks protected/custom tag policy")
        reviewers = policy.get("reviewer_fingerprints")
        if not isinstance(reviewers, list) or not reviewers or any(not SHA256_RE.fullmatch(str(item)) for item in reviewers):
            raise PortalError("environment policy audit lacks required reviewers")
    if set(stage["reviewer_fingerprints"]) & set(release["reviewer_fingerprints"]):
        raise PortalError("environment policy audit reviewers are not distinct")
    expected = audit.get("audit_sha256")
    stripped = {key: value for key, value in audit.items() if key != "audit_sha256"}
    actual = hashlib.sha256(json.dumps(stripped, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if expected != actual:
        raise PortalError("environment policy audit self-hash mismatch")
    return sha256_file(path)


def _verify_consumer_evidence(path: Path, *, mode: str, repository_url: str) -> str:
    evidence = _read_json_object(path, "consumer evidence")
    if evidence.get("format") != CONSUMER_EVIDENCE_FORMAT:
        raise PortalError("invalid consumer evidence format")
    if evidence.get("mode") != mode or evidence.get("repository_url") != repository_url:
        raise PortalError("consumer evidence is not bound to the exact repository")
    if evidence.get("exact_six") != "PASS" or evidence.get("ac08") != "PASS" or evidence.get("native_elf") != "PASS":
        raise PortalError("consumer evidence lacks an exact-six, AC08, or native ELF pass")
    checksums = evidence.get("sha256sums_sha256")
    _require_sha256(checksums, "consumer evidence checksum manifest SHA-256")
    return sha256_file(path)


def _deployment_repository_base(template: str) -> str:
    suffix = "/{relative_path}"
    if not template.endswith(suffix):
        raise PortalError("invalid exact deployment repository")
    return template[: -len(suffix)]


def _run_consumer(
    command: Path,
    *,
    repository_url: str,
    mode: str,
    token_env: str | None,
    gradle_user_home: Path,
    evidence: Path,
    expected_realm_android_library_aar_sha256: str | None = None,
    runner: Callable[[Sequence[str]], None] | None = None,
) -> str:
    if not command.is_file():
        raise PortalError("consumer command does not exist")
    args = [
        str(command),
        "--repository-url",
        repository_url,
        "--mode",
        mode,
        "--gradle-user-home",
        str(gradle_user_home),
        "--evidence-dir",
        str(evidence),
    ]
    if token_env:
        args.extend(("--bearer-env", token_env))
    if expected_realm_android_library_aar_sha256 is not None:
        args.extend(
            ("--expected-realm-android-library-sha256", expected_realm_android_library_aar_sha256)
        )
    try:
        (runner or (lambda values: subprocess.run(values, check=True)))(args)
    except (OSError, subprocess.CalledProcessError) as error:
        raise PortalError("exact deployment consumer failed") from error
    return _verify_consumer_evidence(evidence / "consumer-evidence.json", mode=mode, repository_url=repository_url)


def _decode_json(body: bytes, operation: str) -> Mapping[str, object]:
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PortalError(f"Portal returned invalid JSON while {operation}") from error
    if not isinstance(decoded, dict):
        raise PortalError(f"Portal returned an invalid response while {operation}")
    return decoded


def _urllib_transport(method: str, url: str, headers: Mapping[str, str], data: bytes | None) -> HttpResponse:
    request = Request(url, data=data, method=method, headers=dict(headers))
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - opt-in Portal endpoint only
            return HttpResponse(response.status, response.read(), dict(response.headers.items()))
    except HTTPError as error:
        # Never include response bodies: Portal diagnostics can be unpredictable
        # and must not become a route for credential disclosure.
        return HttpResponse(error.code, b"", dict(error.headers.items()) if error.headers else {})
    except URLError as error:
        raise PortalError("Portal request failed") from error


def _multipart_bundle(bundle: Path) -> tuple[str, bytes]:
    boundary = f"----realm-central-{uuid.uuid4().hex}"
    filename = bundle.name.replace('"', "")
    data = b"".join(
        (
            f"--{boundary}\r\n".encode("ascii"),
            (
                "Content-Disposition: form-data; name=\"bundle\"; "
                f"filename=\"{filename}\"\r\n"
            ).encode("utf-8"),
            b"Content-Type: application/octet-stream\r\n\r\n",
            bundle.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        )
    )
    return boundary, data


class PortalClient:
    """Thin injectable client; it never logs request headers or bodies."""

    def __init__(
        self,
        bearer_token: str,
        *,
        transport: Transport = _urllib_transport,
        base_url: str = PORTAL_URL,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        jitter: Callable[[float], float] | None = None,
    ) -> None:
        try:
            decoded = base64.b64decode(bearer_token, validate=True)
        except (ValueError, TypeError) as error:
            raise PortalError("Portal credential is invalid") from error
        if not decoded or b":" not in decoded:
            raise PortalError("Portal credential is invalid")
        self._bearer_token = bearer_token
        self._transport = transport
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep
        self._clock = clock
        self._jitter = jitter or (lambda delay: delay * random.uniform(0.8, 1.2))
        self.last_poll_trace: list[dict[str, object]] = []

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: bytes | None = None,
        operation: str,
        expected_statuses: frozenset[int] | None = None,
    ) -> HttpResponse:
        request_headers = {
            "Accept": "application/json",
            # The Portal requires the base64 encoding of username:password,
            # supplied as a protected-environment secret, after Bearer.
            "Authorization": f"Bearer {self._bearer_token}",
        }
        if headers:
            request_headers.update(headers)
        response = self._transport(method, f"{self._base_url}{path}", request_headers, data)
        if expected_statuses is not None:
            successful = response.status in expected_statuses
        else:
            successful = 200 <= response.status < 300
        if not successful:
            raise PortalError(f"Portal {operation} request failed (HTTP {response.status})")
        return response

    def upload_user_managed(self, bundle: Path, name: str) -> str:
        boundary, data = _multipart_bundle(bundle)
        query = urlencode({"name": name, "publishingType": "USER_MANAGED"})
        response = self._request(
            "POST",
            f"/api/v1/publisher/upload?{query}",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            data=data,
            operation="upload",
            expected_statuses=frozenset((201,)),
        )
        body = response.body.decode("utf-8", errors="replace").strip()
        if body.startswith("{"):
            decoded = _decode_json(body.encode("utf-8"), "upload")
            body = str(decoded.get("deploymentId", "")).strip()
        if not DEPLOYMENT_ID_RE.fullmatch(body):
            raise PortalError("Portal upload did not return a valid deployment ID")
        return body

    def deployment_status(self, deployment_id: str) -> str:
        return self.deployment_status_with_retry_after(deployment_id)[0]

    def deployment_status_with_retry_after(self, deployment_id: str) -> tuple[str, float | None]:
        self._validate_deployment_id(deployment_id)
        query = urlencode({"id": deployment_id})
        http_response = self._request("POST", f"/api/v1/publisher/status?{query}", operation="status")
        response = _decode_json(
            http_response.body,
            "status",
        )
        state = response.get("deploymentState", response.get("state"))
        if not isinstance(state, str) or not state:
            raise PortalError("Portal status response lacks deployment state")
        retry_after = None
        for header, value in http_response.headers.items():
            if header.lower() != "retry-after":
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                break
            if parsed >= 0:
                retry_after = parsed
            break
        return state.upper(), retry_after

    def poll(
        self,
        deployment_id: str,
        expected: str,
        *,
        attempts: int,
        delay_seconds: float,
        backoff_factor: float = 1.5,
        max_delay_seconds: float = 60.0,
    ) -> str:
        if attempts < 1 or delay_seconds < 0 or backoff_factor < 1 or max_delay_seconds < 0:
            raise PortalError("invalid polling configuration")
        expected = expected.upper()
        self.last_poll_trace = []
        for attempt in range(attempts):
            state, retry_after = self.deployment_status_with_retry_after(deployment_id)
            self.last_poll_trace.append(
                {
                    "attempt": attempt + 1,
                    "deployment_id": deployment_id,
                    "state": state,
                    "observed_at_epoch": int(self._clock()),
                }
            )
            if state == expected:
                return state
            if state == "FAILED":
                raise DeploymentFailed(deployment_id, expected, state)
            if state in {"PUBLISHED", "VALIDATED"}:
                raise PortalError(f"deployment did not reach expected {expected} state")
            if attempt + 1 < attempts:
                if retry_after is not None:
                    delay = retry_after
                else:
                    delay = self._jitter(min(max_delay_seconds, delay_seconds * (backoff_factor**attempt)))
                self._sleep(delay)
        raise PortalError(f"deployment did not reach {expected} within bounded polling")

    def publish(self, deployment_id: str) -> None:
        self._validate_deployment_id(deployment_id)
        encoded = quote(deployment_id, safe="-._~")
        self._request("POST", f"/api/v1/publisher/deployment/{encoded}", operation="publish")

    def deployment_repository(self, deployment_id: str) -> str:
        self._validate_deployment_id(deployment_id)
        encoded = quote(deployment_id, safe="-._~")
        # The Portal's deployment-specific download endpoint is singular and
        # requires a relative artifact path.  It is intentionally not the old
        # plural deployment download API, which could select another release.
        return f"{self._base_url}/api/v1/publisher/deployment/{encoded}/download/{{relative_path}}"

    @staticmethod
    def _validate_deployment_id(deployment_id: str) -> None:
        if not DEPLOYMENT_ID_RE.fullmatch(deployment_id):
            raise PortalError("invalid deployment ID")


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _read_stage_manifest(path: Path, expected_sha256: str) -> Mapping[str, object]:
    _require_sha256(expected_sha256, "stage manifest SHA-256")
    if not path.is_file():
        raise PortalError("stage manifest does not exist")
    if sha256_file(path) != expected_sha256:
        raise PortalError("stage manifest SHA-256 mismatch")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortalError("stage manifest is unreadable") from error
    if not isinstance(manifest, dict) or manifest.get("format") != STAGE_MANIFEST_FORMAT:
        raise PortalError("invalid stage manifest format")
    required = (
        "tag",
        "version",
        "commit",
        "core_commit",
        "bundle_sha256",
        "source_manifest_sha256",
        "realm_android_library_aar_sha256",
        "deployment_id",
        "deployment_repository",
        "publishing_type",
        "validation_state_trace",
        "runtime_provenance",
        "environment_policy_audit_sha256",
        "validated_consumer_evidence_sha256",
    )
    if any(key not in manifest for key in required):
        raise PortalError("stage manifest is incomplete")
    validate_release_binding(
        str(manifest["tag"]),
        str(manifest["version"]),
        str(manifest["commit"]),
        str(manifest["core_commit"]),
    )
    _require_sha256(manifest["bundle_sha256"], "bundle SHA-256")
    _require_sha256(manifest["source_manifest_sha256"], "source manifest SHA-256")
    _require_sha256(manifest["realm_android_library_aar_sha256"], "realm-android-library AAR SHA-256")
    provenance = manifest["runtime_provenance"]
    if not isinstance(provenance, dict):
        raise PortalError("stage manifest lacks runtime provenance")
    if provenance.get("head") != manifest["commit"] or provenance.get("core_commit") != manifest["core_commit"]:
        raise PortalError("stage manifest runtime provenance differs from source binding")
    for field in ("sha256", "wsl_evidence_sha256", "ci_evidence_sha256"):
        _require_sha256(provenance.get(field), f"runtime provenance {field}")
    _require_sha256(manifest["environment_policy_audit_sha256"], "environment policy audit SHA-256")
    _require_sha256(manifest["validated_consumer_evidence_sha256"], "validated consumer evidence SHA-256")
    PortalClient._validate_deployment_id(str(manifest["deployment_id"]))
    if manifest["publishing_type"] != "USER_MANAGED":
        raise PortalError("stage manifest is not USER_MANAGED")
    trace = manifest["validation_state_trace"]
    if (
        not isinstance(trace, list)
        or not trace
        or not isinstance(trace[-1], dict)
        or trace[-1].get("deployment_id") != manifest["deployment_id"]
        or trace[-1].get("state") != "VALIDATED"
    ):
        raise PortalError("stage manifest lacks a validated exact-deployment trace")
    expected_endpoint = (
        r"https://[^/]+/api/v1/publisher/deployment/"
        + re.escape(str(manifest["deployment_id"]))
        + r"/download/\{relative_path\}"
    )
    if not isinstance(manifest["deployment_repository"], str) or not re.fullmatch(expected_endpoint, manifest["deployment_repository"]):
        raise PortalError("invalid exact deployment repository")
    return manifest


def _token_from_environment(token_env: str) -> str:
    token = os.environ.get(token_env)
    if not token:
        # Do not echo an arbitrary environment variable name: callers can pass
        # sensitive names and the workflow already identifies the contract.
        raise PortalError("Portal credential is not configured")
    return token


def _write_first_failure(
    stage_manifest: Path,
    *,
    deployment_id: str,
    expected: str,
    state: str,
    bundle_sha256: str,
    source_manifest_sha256: str,
) -> None:
    """Preserve one redacted stage failure without overwriting the first fact."""

    failure_path = stage_manifest.with_name(stage_manifest.name + ".failed.json")
    evidence = {
        "format": "realm-maven-central-stage-failure-v1",
        "deployment_id": deployment_id,
        "expected_state": expected,
        "observed_state": state,
        "bundle_sha256": bundle_sha256,
        "source_manifest_sha256": source_manifest_sha256,
    }
    try:
        with failure_path.open("x", encoding="utf-8") as destination:
            destination.write(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")
    except FileExistsError:
        pass


def stage(
    *,
    bundle: Path,
    source_manifest: Path,
    tag: str,
    version: str,
    commit: str,
    core_commit: str,
    runtime_provenance: Path,
    environment_policy_audit: Path,
    validated_consumer_command: Path,
    validated_consumer_gradle_home: Path,
    validated_consumer_evidence: Path,
    stage_manifest: Path,
    token_env: str,
    allow_network: bool,
    attempts: int,
    delay_seconds: float,
    backoff_factor: float = 1.5,
    max_delay_seconds: float = 60.0,
    client: PortalClient | None = None,
    consumer_runner: Callable[[Sequence[str]], None] | None = None,
) -> Mapping[str, object]:
    validate_release_binding(tag, version, commit, core_commit)
    failure_path = stage_manifest.with_name(stage_manifest.name + ".failed.json")
    if stage_manifest.exists() or failure_path.exists():
        raise PortalError("stage manifest already has an upload outcome")
    bundle_sha256, source_manifest_sha256 = verify_bundle_binding(bundle, source_manifest)
    realm_android_library_aar_sha256_value = realm_android_library_aar_sha256(bundle, version)
    provenance = verify_runtime_provenance(runtime_provenance, commit, core_commit)
    policy_audit_sha256 = verify_environment_policy_audit(environment_policy_audit)
    if not allow_network:
        raise PortalError("network access requires --allow-network")
    client = client or PortalClient(_token_from_environment(token_env))
    deployment_id = client.upload_user_managed(bundle, tag)
    try:
        client.poll(
            deployment_id,
            "VALIDATED",
            attempts=attempts,
            delay_seconds=delay_seconds,
            backoff_factor=backoff_factor,
            max_delay_seconds=max_delay_seconds,
        )
    except DeploymentFailed as error:
        _write_first_failure(
            stage_manifest,
            deployment_id=error.deployment_id,
            expected=error.expected,
            state=error.state,
            bundle_sha256=bundle_sha256,
            source_manifest_sha256=source_manifest_sha256,
        )
        raise
    repository_template = client.deployment_repository(deployment_id)
    repository_url = _deployment_repository_base(repository_template)
    try:
        validated_consumer_evidence_sha256 = _run_consumer(
            validated_consumer_command,
            repository_url=repository_url,
            mode="validated",
            token_env=token_env,
            gradle_user_home=validated_consumer_gradle_home,
            evidence=validated_consumer_evidence,
            runner=consumer_runner,
        )
    except PortalError:
        # A successful upload followed by a failed consumer must be durable
        # evidence too; otherwise a rerun could silently create deployment #2.
        _write_first_failure(
            stage_manifest,
            deployment_id=deployment_id,
            expected="CONSUMER_PASS",
            state="VALIDATED",
            bundle_sha256=bundle_sha256,
            source_manifest_sha256=source_manifest_sha256,
        )
        raise
    manifest: dict[str, object] = {
        "format": STAGE_MANIFEST_FORMAT,
        "tag": tag,
        "version": version,
        "commit": commit,
        "core_commit": core_commit,
        "bundle_sha256": bundle_sha256,
        "source_manifest_sha256": source_manifest_sha256,
        "realm_android_library_aar_sha256": realm_android_library_aar_sha256_value,
        "runtime_provenance": provenance,
        "environment_policy_audit_sha256": policy_audit_sha256,
        "validated_consumer_evidence_sha256": validated_consumer_evidence_sha256,
        "deployment_id": deployment_id,
        "publishing_type": "USER_MANAGED",
        "deployment_repository": repository_template,
        "validation_state_trace": client.last_poll_trace,
    }
    _write_json(stage_manifest, manifest)
    return {
        "deployment_id": deployment_id,
        "deployment_repository": manifest["deployment_repository"],
        "stage_manifest_sha256": sha256_file(stage_manifest),
    }


def release(
    *,
    stage_manifest: Path,
    stage_manifest_sha256: str,
    token_env: str,
    allow_network: bool,
    attempts: int,
    delay_seconds: float,
    backoff_factor: float = 1.5,
    max_delay_seconds: float = 60.0,
    client: PortalClient | None = None,
    published_consumer_command: Path | None = None,
    published_consumer_gradle_home: Path | None = None,
    published_consumer_evidence: Path | None = None,
    consumer_runner: Callable[[Sequence[str]], None] | None = None,
) -> Mapping[str, object]:
    manifest = _read_stage_manifest(stage_manifest, stage_manifest_sha256)
    if not allow_network:
        raise PortalError("network access requires --allow-network")
    client = client or PortalClient(_token_from_environment(token_env))
    deployment_id = str(manifest["deployment_id"])
    # The release gate independently proves the exact deployment is still the
    # staged, USER_MANAGED deployment before it can call the publish endpoint.
    client.poll(
        deployment_id,
        "VALIDATED",
        attempts=attempts,
        delay_seconds=delay_seconds,
        backoff_factor=backoff_factor,
        max_delay_seconds=max_delay_seconds,
    )
    client.publish(deployment_id)
    client.poll(
        deployment_id,
        "PUBLISHED",
        attempts=attempts,
        delay_seconds=delay_seconds,
        backoff_factor=backoff_factor,
        max_delay_seconds=max_delay_seconds,
    )
    if not (published_consumer_command and published_consumer_gradle_home and published_consumer_evidence):
        raise PortalError("published consumer gate is required")
    consumer_sha256 = _run_consumer(
        published_consumer_command,
        repository_url="https://repo1.maven.org/maven2",
        mode="central",
        token_env=None,
        gradle_user_home=published_consumer_gradle_home,
        evidence=published_consumer_evidence,
        expected_realm_android_library_aar_sha256=str(manifest["realm_android_library_aar_sha256"]),
        runner=consumer_runner,
    )
    return {"deployment_id": deployment_id, "state": "PUBLISHED", "published_consumer_evidence_sha256": consumer_sha256}


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    verify = commands.add_parser("verify-bundle", help="verify exact source-manifest/bundle binding")
    verify.add_argument("--bundle", required=True, type=Path)
    verify.add_argument("--source-manifest", required=True, type=Path)

    policy = commands.add_parser("audit-environment-policy", help="write a redacted, hashed environment-policy audit")
    policy.add_argument("--stage-policy", required=True, type=Path)
    policy.add_argument("--release-policy", required=True, type=Path)
    policy.add_argument("--audit-file", required=True, type=Path)

    stage_parser = commands.add_parser("stage", help="upload one USER_MANAGED deployment and wait for VALIDATED")
    stage_parser.add_argument("--bundle", required=True, type=Path)
    stage_parser.add_argument("--source-manifest", required=True, type=Path)
    stage_parser.add_argument("--tag", required=True)
    stage_parser.add_argument("--version", required=True)
    stage_parser.add_argument("--commit", required=True)
    stage_parser.add_argument("--core-commit", required=True)
    stage_parser.add_argument("--runtime-provenance", required=True, type=Path)
    stage_parser.add_argument("--environment-policy-audit", required=True, type=Path)
    stage_parser.add_argument("--validated-consumer-command", required=True, type=Path)
    stage_parser.add_argument("--validated-consumer-gradle-home", required=True, type=Path)
    stage_parser.add_argument("--validated-consumer-evidence", required=True, type=Path)
    stage_parser.add_argument("--stage-manifest", required=True, type=Path)
    stage_parser.add_argument("--token-env", default="CENTRAL_PORTAL_TOKEN")
    stage_parser.add_argument("--poll-attempts", default=12, type=_positive_int)
    stage_parser.add_argument("--poll-delay-seconds", default=5.0, type=float)
    stage_parser.add_argument("--poll-backoff-factor", default=1.5, type=float)
    stage_parser.add_argument("--poll-max-delay-seconds", default=60.0, type=float)
    stage_parser.add_argument("--allow-network", action="store_true")

    release_parser = commands.add_parser("release", help="publish the exact deployment in a staged manifest")
    release_parser.add_argument("--stage-manifest", required=True, type=Path)
    release_parser.add_argument("--stage-manifest-sha256", required=True)
    release_parser.add_argument("--published-consumer-command", required=True, type=Path)
    release_parser.add_argument("--published-consumer-gradle-home", required=True, type=Path)
    release_parser.add_argument("--published-consumer-evidence", required=True, type=Path)
    release_parser.add_argument("--token-env", default="CENTRAL_PORTAL_TOKEN")
    release_parser.add_argument("--poll-attempts", default=12, type=_positive_int)
    release_parser.add_argument("--poll-delay-seconds", default=5.0, type=float)
    release_parser.add_argument("--poll-backoff-factor", default=1.5, type=float)
    release_parser.add_argument("--poll-max-delay-seconds", default=60.0, type=float)
    release_parser.add_argument("--allow-network", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "verify-bundle":
            bundle_sha256, source_manifest_sha256 = verify_bundle_binding(args.bundle, args.source_manifest)
            result: Mapping[str, object] = {
                "status": "VERIFIED",
                "bundle_sha256": bundle_sha256,
                "source_manifest_sha256": source_manifest_sha256,
            }
        elif args.command == "audit-environment-policy":
            result = {
                "status": "VERIFIED",
                "environment_policy_audit_sha256": write_environment_policy_audit(
                    args.stage_policy, args.release_policy, args.audit_file
                ),
            }
        elif args.command == "stage":
            result = stage(
                bundle=args.bundle,
                source_manifest=args.source_manifest,
                tag=args.tag,
                version=args.version,
                commit=args.commit,
                core_commit=args.core_commit,
                runtime_provenance=args.runtime_provenance,
                environment_policy_audit=args.environment_policy_audit,
                validated_consumer_command=args.validated_consumer_command,
                validated_consumer_gradle_home=args.validated_consumer_gradle_home,
                validated_consumer_evidence=args.validated_consumer_evidence,
                stage_manifest=args.stage_manifest,
                token_env=args.token_env,
                allow_network=args.allow_network,
                attempts=args.poll_attempts,
                delay_seconds=args.poll_delay_seconds,
                backoff_factor=args.poll_backoff_factor,
                max_delay_seconds=args.poll_max_delay_seconds,
            )
        else:
            result = release(
                stage_manifest=args.stage_manifest,
                stage_manifest_sha256=args.stage_manifest_sha256,
                token_env=args.token_env,
                allow_network=args.allow_network,
                attempts=args.poll_attempts,
                delay_seconds=args.poll_delay_seconds,
                backoff_factor=args.poll_backoff_factor,
                max_delay_seconds=args.poll_max_delay_seconds,
                published_consumer_command=args.published_consumer_command,
                published_consumer_gradle_home=args.published_consumer_gradle_home,
                published_consumer_evidence=args.published_consumer_evidence,
            )
    except PortalError as error:
        print(f"central portal: FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
