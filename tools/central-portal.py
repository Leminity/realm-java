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
from datetime import datetime, timezone
from fnmatch import fnmatchcase
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
from urllib.parse import quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen
import uuid
import zipfile


PORTAL_URL = "https://central.sonatype.com"
TAG_RE = re.compile(r"^v10\.19\.0-agp9\.[1-9][0-9]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
STAGE_MANIFEST_FORMAT = "realm-maven-central-stage-v3"
STAGE_PREPARED_FORMAT = "realm-maven-central-stage-prepared-v1"
RELEASE_PREPARED_FORMAT = "realm-maven-central-release-prepared-v1"
POLICY_AUDIT_FORMAT = "realm-maven-central-environment-policy-audit-v1"
ADMIN_BYPASS_ATTESTATION_FORMAT = "realm-github-environment-admin-bypass-attestation-v1"
CONSUMER_EVIDENCE_FORMAT = "realm-maven-central-consumer-evidence-v1"
MIRROR_EVIDENCE_FORMAT = "realm-maven-central-validated-mirror-v1"
RUNTIME_PROVENANCE_SCHEMA_VERSION = 2
APPROVED_DEPLOYMENT_TAG_PATTERN = "v10.19.0-agp9.*"
ADMIN_BYPASS_PROOF_MAX_AGE_SECONDS = 15 * 60
RUNTIME_GATE_PATHS = (
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "tools/central-portal.py",
    "tools/test-central-portal.py",
)


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
ConsumerRunner = Callable[[Sequence[str], Mapping[str, str]], None]


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


def _require_positive_decimal(value: object, field: str) -> str:
    rendered = str(value)
    if not rendered.isdecimal() or int(rendered) < 1:
        raise PortalError(f"invalid {field}")
    return rendered


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


def verify_runtime_provenance(path: Path, commit: str, core_commit: str) -> Mapping[str, str]:
    """Verify Task35's exact schema-v2 runtime provenance handoff."""

    provenance = _read_json_object(path, "runtime provenance")
    if provenance.get("schema_version") != RUNTIME_PROVENANCE_SCHEMA_VERSION:
        raise PortalError("runtime provenance has an unsupported schema version")
    if provenance.get("manifest_kind") != "runtime":
        raise PortalError("runtime provenance is not a runtime manifest")
    source = provenance.get("source")
    wsl = provenance.get("wsl")
    ci = provenance.get("ci")
    gate_digests = provenance.get("gate_digests")
    if not all(isinstance(value, dict) for value in (source, wsl, ci, gate_digests)):
        raise PortalError("runtime provenance is incomplete")
    head = source.get("current_head_commit")
    bound_core = source.get("core_commit")
    core_gitlink = source.get("core_gitlink")
    core_submodules = source.get("core_submodules")
    if head != commit or bound_core != core_commit or core_gitlink != core_commit:
        raise PortalError("runtime provenance source binding differs from release source")
    if (
        not isinstance(core_submodules, dict)
        or set(core_submodules) != {"external/catch", "src/external/sha-1", "src/external/sha-2"}
        or any(not isinstance(value, str) or not GIT_SHA_RE.fullmatch(value) for value in core_submodules.values())
    ):
        raise PortalError("runtime provenance lacks exact Core submodule bindings")
    if ci.get("checksum_verified") is not True:
        raise PortalError("runtime provenance CI checksums are not independently verified")
    required_exact = ci.get("required_exact")
    required_prefixes = ci.get("required_prefixes")
    files = ci.get("files")
    if not isinstance(required_exact, list) or not required_exact or not isinstance(required_prefixes, list) or not required_prefixes:
        raise PortalError("runtime provenance lacks required CI evidence contracts")
    if not isinstance(files, dict) or any(not SHA256_RE.fullmatch(str(value)) for value in files.values()):
        raise PortalError("runtime provenance lacks checksummed CI evidence files")
    for required_path in RUNTIME_GATE_PATHS:
        _require_sha256(gate_digests.get(required_path), f"runtime provenance gate digest {required_path}")
    canonical_gates = json.dumps(gate_digests, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "sha256": sha256_file(path),
        "head": _require_git_sha(head, "runtime provenance head"),
        "core_commit": _require_git_sha(bound_core, "runtime provenance core commit"),
        "wsl_evidence_sha256": _require_sha256(
            wsl.get("runtime_sha256"), "runtime provenance WSL evidence SHA-256"
        ),
        "wsl_environment_sha256": _require_sha256(
            wsl.get("environment_sha256"), "runtime provenance WSL environment SHA-256"
        ),
        "ci_evidence_tree_sha256": _require_sha256(
            ci.get("tree_sha256"), "runtime provenance CI evidence tree SHA-256"
        ),
        "ci_checksum_manifest_sha256": _require_sha256(
            ci.get("checksum_manifest_sha256"), "runtime provenance CI checksum manifest SHA-256"
        ),
        "gate_digests_sha256": hashlib.sha256(canonical_gates).hexdigest(),
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


def _admin_bypass_proof(
    policy: Mapping[str, object],
    attestation: Mapping[str, object] | None,
    *,
    repository: str,
    environment: str,
    gate_time: datetime,
) -> Mapping[str, object]:
    """Fail closed unless the current environment proves admin bypass is off.

    GitHub's documented environment response does not consistently expose this
    setting.  When the server returns it directly, that value is authoritative.
    Otherwise an independently captured GitHub security/audit-log prerequisite
    must bind the exact repository, environment, and current ``updated_at``.
    Any later environment edit therefore invalidates the prerequisite.
    """

    updated_at = policy.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at:
        raise PortalError(f"{environment}: environment updated_at is unavailable")
    direct = policy.get("can_admins_bypass")
    if direct is True:
        raise PortalError(f"{environment}: administrator bypass is enabled")
    if direct is False:
        proof = {
            "source": "github-environment-api",
            "repository": repository,
            "environment": environment,
            "environment_updated_at": updated_at,
            "can_admins_bypass": False,
        }
        canonical = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {
            "admin_bypass_disabled": True,
            "admin_bypass_proof_source": proof["source"],
            "admin_bypass_proof_sha256": hashlib.sha256(canonical).hexdigest(),
            "environment_updated_at": updated_at,
        }
    if attestation is None:
        raise PortalError(f"{environment}: administrator bypass state is unproven")
    if (
        attestation.get("format") != ADMIN_BYPASS_ATTESTATION_FORMAT
        or attestation.get("repository") != repository
    ):
        raise PortalError(f"{environment}: administrator bypass attestation is invalid")
    source = attestation.get("source_kind")
    if source not in {"user-export", "org-export", "org-api", "enterprise-stream"}:
        raise PortalError(f"{environment}: administrator bypass attestation source is untrusted")
    if attestation.get("complete") is not True:
        raise PortalError(f"{environment}: administrator bypass log coverage is incomplete")

    def parse_timestamp(value: object, field: str) -> datetime:
        if not isinstance(value, str):
            raise PortalError(f"{environment}: invalid administrator bypass {field}")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PortalError(f"{environment}: invalid administrator bypass {field}") from error
        if parsed.tzinfo is None:
            raise PortalError(f"{environment}: invalid administrator bypass {field}")
        return parsed.astimezone(timezone.utc)

    coverage_start = parse_timestamp(attestation.get("coverage_start"), "coverage_start")
    coverage_end = parse_timestamp(attestation.get("coverage_end"), "coverage_end")
    policy_updated_at = parse_timestamp(updated_at, "environment updated_at")
    if coverage_start > coverage_end:
        raise PortalError(f"{environment}: administrator bypass log coverage is invalid")
    if coverage_end < policy_updated_at:
        raise PortalError(f"{environment}: administrator bypass log does not cover the live policy")
    age_seconds = (gate_time - coverage_end).total_seconds()
    if age_seconds < -60 or age_seconds > ADMIN_BYPASS_PROOF_MAX_AGE_SECONDS:
        raise PortalError(f"{environment}: administrator bypass log coverage is stale")
    events = attestation.get("events")
    if not isinstance(events, list) or not events:
        raise PortalError(f"{environment}: administrator bypass log has no events")

    def event_value(event: Mapping[str, object], *names: str) -> object:
        nested = event.get("data")
        nested_map = nested if isinstance(nested, dict) else {}
        values: list[object] = []
        for name in names:
            if name in event:
                values.append(event[name])
            if name in nested_map:
                values.append(nested_map[name])
        if not values:
            return None
        first = values[0]
        if any(value != first for value in values[1:]):
            raise PortalError(f"{environment}: administrator bypass log fields conflict")
        return first

    environment_id = policy.get("id")
    if environment_id is None:
        raise PortalError(f"{environment}: environment id is unavailable")
    relevant: list[tuple[datetime, str, object]] = []
    for raw_event in events:
        if not isinstance(raw_event, dict):
            raise PortalError(f"{environment}: administrator bypass log event is invalid")
        event_repository = event_value(raw_event, "repo", "repository")
        event_environment = event_value(raw_event, "environment_name")
        if event_repository != repository or event_environment != environment:
            continue
        event_time = parse_timestamp(
            event_value(raw_event, "@timestamp", "created_at"), "event timestamp"
        )
        if not (coverage_start <= event_time <= coverage_end):
            raise PortalError(f"{environment}: administrator bypass event is outside log coverage")
        event_id = event_value(raw_event, "environment_id")
        if str(event_id) != str(environment_id):
            raise PortalError(f"{environment}: administrator bypass evidence binds another environment")
        action = event_value(raw_event, "action")
        if action == "environment.delete":
            relevant.append((event_time, str(action), None))
        elif action == "environment.update_protection_rule":
            bypass = event_value(raw_event, "can_admins_bypass", "new_value")
            if not isinstance(bypass, bool):
                raise PortalError(f"{environment}: administrator bypass event is ambiguous")
            relevant.append((event_time, str(action), bypass))
    if not relevant:
        raise PortalError(f"{environment}: administrator bypass event is missing")
    _, latest_action, latest_bypass = max(relevant, key=lambda item: item[0])
    if latest_action != "environment.update_protection_rule" or latest_bypass is not False:
        raise PortalError(f"{environment}: administrator bypass is not disabled")
    canonical = json.dumps(
        {
            "format": ADMIN_BYPASS_ATTESTATION_FORMAT,
            "repository": repository,
            "environment": environment,
            "environment_id": str(environment_id),
            "environment_updated_at": updated_at,
            "can_admins_bypass": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "admin_bypass_disabled": True,
        "admin_bypass_proof_source": source,
        "admin_bypass_proof_sha256": hashlib.sha256(canonical).hexdigest(),
        "environment_updated_at": updated_at,
    }


def _environment_policy_summary(
    policy: Mapping[str, object],
    deployment_policies: Mapping[str, object],
    admin_bypass_attestation: Mapping[str, object] | None,
    repository: str,
    environment: str,
    release_tag: str,
    gate_time: datetime,
) -> Mapping[str, object]:
    reviewers = _reviewer_fingerprints(policy, environment)
    branch_policy = policy.get("deployment_branch_policy")
    if not isinstance(branch_policy, dict) or not (
        branch_policy.get("protected_branches") is False
        and branch_policy.get("custom_branch_policies") is True
    ):
        raise PortalError(f"{environment}: exact custom tag policy is not enabled")
    raw_policies = deployment_policies.get("branch_policies")
    if (
        not isinstance(raw_policies, list)
        or deployment_policies.get("total_count") != len(raw_policies)
        or len(raw_policies) != 1
    ):
        raise PortalError(f"{environment}: custom tag policy list is missing")
    names = {
        item.get("name")
        for item in raw_policies
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if names != {APPROVED_DEPLOYMENT_TAG_PATTERN} or not fnmatchcase(
        release_tag, APPROVED_DEPLOYMENT_TAG_PATTERN
    ):
        raise PortalError(f"{environment}: custom tag policy differs from the approved release family")
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
        "release_tag": release_tag,
        "deployment_tag_policy_sha256": hashlib.sha256(
            APPROVED_DEPLOYMENT_TAG_PATTERN.encode("utf-8")
        ).hexdigest(),
        **_admin_bypass_proof(
            policy,
            admin_bypass_attestation,
            repository=repository,
            environment=environment,
            gate_time=gate_time,
        ),
    }


def write_environment_policy_audit(
    stage_policy: Path,
    stage_deployment_policies: Path,
    release_policy: Path,
    release_deployment_policies: Path,
    repository: str,
    admin_bypass_attestation: Path | None,
    gate_time: str,
    release_tag: str,
    audit_file: Path,
) -> str:
    """Create a redacted, self-hashed proof of the server-side environment rules."""

    if not TAG_RE.fullmatch(release_tag):
        raise PortalError("environment policy audit tag is outside the approved release family")
    if not repository or "/" not in repository:
        raise PortalError("environment policy audit repository is invalid")
    attestation = (
        _read_json_object(admin_bypass_attestation, "administrator bypass attestation")
        if admin_bypass_attestation is not None
        else None
    )
    try:
        parsed_gate_time = datetime.fromisoformat(gate_time.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise PortalError("environment policy audit gate time is invalid") from error
    if parsed_gate_time.tzinfo is None:
        raise PortalError("environment policy audit gate time is invalid")
    parsed_gate_time = parsed_gate_time.astimezone(timezone.utc)
    stage = _environment_policy_summary(
        _read_json_object(stage_policy, "stage environment policy"),
        _read_json_object(stage_deployment_policies, "stage deployment policies"),
        attestation,
        repository,
        "maven-central-stage",
        release_tag,
        parsed_gate_time,
    )
    release = _environment_policy_summary(
        _read_json_object(release_policy, "release environment policy"),
        _read_json_object(release_deployment_policies, "release deployment policies"),
        attestation,
        repository,
        "maven-central-release",
        release_tag,
        parsed_gate_time,
    )
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
        if policy.get("admin_bypass_disabled") is not True:
            raise PortalError("environment policy audit lacks disabled administrator bypass")
        if policy.get("admin_bypass_proof_source") not in {
            "github-environment-api",
            "user-export",
            "org-export",
            "org-api",
            "enterprise-stream",
        }:
            raise PortalError("environment policy audit has an invalid administrator bypass proof")
        _require_sha256(
            policy.get("admin_bypass_proof_sha256"),
            "environment policy administrator bypass proof SHA-256",
        )
        if not isinstance(policy.get("environment_updated_at"), str) or not policy["environment_updated_at"]:
            raise PortalError("environment policy audit lacks environment update binding")
        if not TAG_RE.fullmatch(str(policy.get("release_tag", ""))):
            raise PortalError("environment policy audit lacks the approved release tag")
        expected_policy_sha = hashlib.sha256(APPROVED_DEPLOYMENT_TAG_PATTERN.encode("utf-8")).hexdigest()
        if policy.get("deployment_tag_policy_sha256") != expected_policy_sha:
            raise PortalError("environment policy audit tag policy differs")
        reviewers = policy.get("reviewer_fingerprints")
        if not isinstance(reviewers, list) or not reviewers or any(not SHA256_RE.fullmatch(str(item)) for item in reviewers):
            raise PortalError("environment policy audit lacks required reviewers")
    if set(stage["reviewer_fingerprints"]) & set(release["reviewer_fingerprints"]):
        raise PortalError("environment policy audit reviewers are not distinct")
    if stage["release_tag"] != release["release_tag"]:
        raise PortalError("environment policy audit tags differ")
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


_CONSUMER_ENV_ALLOWLIST = frozenset(
    {
        "ANDROID_HOME",
        "ANDROID_SDK_ROOT",
        "CI",
        "EMULATOR_RUNTIME_LIB_DIR",
        "G011_OFFICIAL_ENCRYPTED_REALM",
        "G011_OFFICIAL_GRADLE_75",
        "G011_OFFICIAL_GRADLE_HOME_ARCHIVE",
        "G011_OFFICIAL_GRADLE_HOME_ARCHIVE_SHA256",
        "GITHUB_ACTIONS",
        "GITHUB_REF",
        "GITHUB_REPOSITORY",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_RUN_ID",
        "JAVA_HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "PATH",
        "SHELL",
        "TMP",
        "TEMP",
        "TMPDIR",
        "USER",
    }
)


_PROTECTED_PROCESS_ENV_NAMES = frozenset(
    {
        "CENTRAL_PORTAL_BEARER_TOKEN",
        "CENTRAL_PORTAL_TOKEN",
        "PORTAL_TOKEN",
        "G011_ENVIRONMENT_POLICY_TOKEN",
        "G011_ENVIRONMENT_BYPASS_ATTESTATION",
        "POLICY_TOKEN",
        "BYPASS_ATTESTATION",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "MAVEN_SIGNING_KEY",
        "MAVEN_SIGNING_PASSWORD",
        "SIGNING_KEY",
        "SIGNING_PASSWORD",
        "g008SigningKey",
        "g008SigningPassword",
    }
)


def _consumer_environment(gradle_user_home: Path, token_env: str) -> dict[str, str]:
    child = {name: os.environ[name] for name in _CONSUMER_ENV_ALLOWLIST if name in os.environ}
    isolated_home = gradle_user_home / "process-home"
    isolated_home.mkdir(parents=True, exist_ok=True)
    child["HOME"] = str(isolated_home)
    child["GRADLE_USER_HOME"] = str(gradle_user_home)
    # These names are intentionally checked even though the allowlist already
    # excludes them.  The assertions make future allowlist edits fail closed.
    forbidden_names = set(_PROTECTED_PROCESS_ENV_NAMES) | {token_env}
    for name in forbidden_names:
        child.pop(name, None)
    if forbidden_names & set(child):
        raise PortalError("consumer environment contains protected credentials")
    return child


def _run_consumer(
    command: Path,
    *,
    repository_url: str,
    mode: str,
    token_env: str,
    gradle_user_home: Path,
    evidence: Path,
    expected_realm_android_library_aar_sha256: str | None = None,
    runner: ConsumerRunner | None = None,
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
    if expected_realm_android_library_aar_sha256 is not None:
        args.extend(
            ("--expected-realm-android-library-sha256", expected_realm_android_library_aar_sha256)
        )
    try:
        child_env = _consumer_environment(gradle_user_home, token_env)
        (runner or (lambda values, env: subprocess.run(values, check=True, env=dict(env))))(
            args, child_env
        )
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
        deadline_seconds: float = 900.0,
    ) -> str:
        if (
            attempts < 1
            or delay_seconds < 0
            or backoff_factor < 1
            or max_delay_seconds < 0
            or deadline_seconds <= 0
        ):
            raise PortalError("invalid polling configuration")
        expected = expected.upper()
        self.last_poll_trace = []
        deadline = self._clock() + deadline_seconds
        for attempt in range(attempts):
            if self._clock() >= deadline:
                raise PortalError(f"deployment did not reach {expected} within bounded polling deadline")
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
            if expected == "VALIDATED" and state in {"PUBLISHING", "PUBLISHED"}:
                raise PortalError(f"deployment did not reach expected {expected} state")
            if expected != "PUBLISHED" and state in {"PUBLISHED", "VALIDATED"}:
                raise PortalError(f"deployment did not reach expected {expected} state")
            if attempt + 1 < attempts:
                if retry_after is not None:
                    delay = retry_after
                else:
                    delay = self._jitter(min(max_delay_seconds, delay_seconds * (backoff_factor**attempt)))
                remaining = deadline - self._clock()
                if delay > remaining:
                    raise PortalError(
                        f"deployment did not reach {expected} within bounded polling deadline"
                    )
                self._sleep(delay)
        raise PortalError(f"deployment did not reach {expected} within bounded polling")

    def publish(self, deployment_id: str) -> None:
        self._validate_deployment_id(deployment_id)
        encoded = quote(deployment_id, safe="-._~")
        self._request("POST", f"/api/v1/publisher/deployment/{encoded}", operation="publish")

    def drop(self, deployment_id: str) -> None:
        """Drop one evidenced, unpublished deployment after a failed gate."""

        self._validate_deployment_id(deployment_id)
        encoded = quote(deployment_id, safe="-._~")
        self._request("DELETE", f"/api/v1/publisher/deployment/{encoded}", operation="drop")

    def deployment_repository(self, deployment_id: str) -> str:
        self._validate_deployment_id(deployment_id)
        encoded = quote(deployment_id, safe="-._~")
        # The Portal's deployment-specific download endpoint is singular and
        # requires a relative artifact path.  It is intentionally not the old
        # plural deployment download API, which could select another release.
        return f"{self._base_url}/api/v1/publisher/deployment/{encoded}/download/{{relative_path}}"

    def download(self, deployment_id: str, relative_path: str) -> bytes:
        self._validate_deployment_id(deployment_id)
        if (
            not relative_path
            or relative_path.startswith("/")
            or any(part in {"", ".", ".."} for part in relative_path.split("/"))
        ):
            raise PortalError("invalid deployment download path")
        encoded_deployment = quote(deployment_id, safe="-._~")
        encoded_path = quote(relative_path, safe="/-._~")
        response = self._request(
            "GET",
            f"/api/v1/publisher/deployment/{encoded_deployment}/download/{encoded_path}",
            headers={"Accept": "application/octet-stream"},
            operation="download",
        )
        return response.body

    @staticmethod
    def _validate_deployment_id(deployment_id: str) -> None:
        if not DEPLOYMENT_ID_RE.fullmatch(deployment_id):
            raise PortalError("invalid deployment ID")


def _materialize_verified_deployment_mirror(
    client: PortalClient,
    *,
    deployment_id: str,
    source_manifest: Path,
    evidence_root: Path,
) -> tuple[str, str]:
    """Download the exact validated deployment in the trusted parent process.

    The Portal credential never crosses into Gradle, the Realm plugin, or the
    runtime fixture.  The token-bearing parent verifies every remote byte
    against the already signed source manifest, then the untrusted consumer
    receives only a local file repository.
    """

    manifest = _read_json_object(source_manifest, "source manifest")
    expected = _safe_manifest_paths(manifest)
    mirror = evidence_root / "validated-deployment-mirror"
    if mirror.exists() and any(mirror.iterdir()):
        raise PortalError("validated deployment mirror is not empty")
    mirror.mkdir(parents=True, exist_ok=True)
    materialized: list[dict[str, object]] = []
    for relative_path, expected_sha256 in sorted(expected.items()):
        contents = client.download(deployment_id, relative_path)
        actual_sha256 = hashlib.sha256(contents).hexdigest()
        if actual_sha256 != expected_sha256:
            raise PortalError("validated deployment download differs from source manifest")
        destination = mirror.joinpath(*relative_path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        temporary.write_bytes(contents)
        os.replace(temporary, destination)
        materialized.append(
            {"path": relative_path, "sha256": actual_sha256, "size": len(contents)}
        )
    files_canonical = json.dumps(
        materialized, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    evidence = {
        "format": MIRROR_EVIDENCE_FORMAT,
        "deployment_id": deployment_id,
        "deployment_repository": client.deployment_repository(deployment_id),
        "source_manifest_sha256": sha256_file(source_manifest),
        "files": materialized,
        "files_sha256": hashlib.sha256(files_canonical).hexdigest(),
    }
    evidence_path = evidence_root / "validated-deployment-mirror-evidence.json"
    _write_json(evidence_path, evidence)
    return mirror.resolve().as_uri(), sha256_file(evidence_path)


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _assert_tokenless_process() -> None:
    """Fail closed unless this process and readable ancestors lack release secrets.

    Scrubbing only a subprocess environment is insufficient on Linux because a
    same-UID child can read its token-bearing parent's ``/proc/<pid>/environ``.
    Consumer commands therefore run only in a separate workflow step/process
    after the Portal-only process has exited.
    """

    if _PROTECTED_PROCESS_ENV_NAMES & set(os.environ):
        raise PortalError("tokenless consumer process contains protected credential variables")
    proc = Path("/proc")
    pid = os.getppid()
    visited: set[int] = set()
    while proc.is_dir() and pid > 1 and pid not in visited:
        visited.add(pid)
        try:
            status_lines = (proc / str(pid) / "status").read_text(encoding="utf-8").splitlines()
            uid_line = next(line for line in status_lines if line.startswith("Uid:"))
            ancestor_uid = int(uid_line.split()[1])
            if ancestor_uid != os.getuid():
                break
            names = {
                entry.split(b"=", 1)[0].decode("utf-8", "ignore")
                for entry in (proc / str(pid) / "environ").read_bytes().split(b"\0")
                if b"=" in entry
            }
        except (OSError, StopIteration, ValueError, IndexError) as error:
            raise PortalError("cannot verify tokenless consumer process ancestry") from error
        if _PROTECTED_PROCESS_ENV_NAMES & names:
            raise PortalError("tokenless consumer ancestor contains protected credential variables")
        try:
            stat = (proc / str(pid) / "stat").read_text(encoding="utf-8")
            fields = stat.rsplit(")", 1)[1].split()
            pid = int(fields[1])
        except (OSError, ValueError, IndexError) as error:
            raise PortalError("cannot verify tokenless consumer process ancestry") from error


def _read_hashed_json(path: Path, expected_sha256: str, *, label: str) -> dict[str, object]:
    _require_sha256(expected_sha256, f"{label} SHA-256")
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise PortalError(f"{label} SHA-256 mismatch")
    value = _read_json_object(path, label)
    return dict(value)


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
        "ci_artifact_sha256",
        "ci_run_id",
        "ci_artifact_id",
        "environment_policy_audit_sha256",
        "validated_deployment_mirror_evidence_sha256",
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
    for field in (
        "sha256",
        "wsl_evidence_sha256",
        "wsl_environment_sha256",
        "ci_evidence_tree_sha256",
        "ci_checksum_manifest_sha256",
        "gate_digests_sha256",
    ):
        _require_sha256(provenance.get(field), f"runtime provenance {field}")
    _require_sha256(manifest["ci_artifact_sha256"], "CI artifact SHA-256")
    _require_positive_decimal(manifest["ci_run_id"], "CI run ID")
    _require_positive_decimal(manifest["ci_artifact_id"], "CI artifact ID")
    _require_sha256(manifest["environment_policy_audit_sha256"], "environment policy audit SHA-256")
    _require_sha256(
        manifest["validated_deployment_mirror_evidence_sha256"],
        "validated deployment mirror evidence SHA-256",
    )
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
        f"{PORTAL_URL}/api/v1/publisher/deployment/"
        f"{manifest['deployment_id']}/download/{{relative_path}}"
    )
    if manifest["deployment_repository"] != expected_endpoint:
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
    state_trace: Sequence[Mapping[str, object]] = (),
    drop_failed_deployment: bool = False,
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
        "state_trace": list(state_trace),
        "drop_policy": (
            "drop-after-evidence"
            if drop_failed_deployment
            else "retain-for-support-or-manual-recovery"
        ),
    }
    try:
        with failure_path.open("x", encoding="utf-8") as destination:
            destination.write(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")
    except FileExistsError:
        pass


def _validate_prepared_stage(value: Mapping[str, object]) -> dict[str, object]:
    if value.get("format") != STAGE_PREPARED_FORMAT:
        raise PortalError("invalid prepared stage format")
    required = (
        "tag", "version", "commit", "core_commit", "bundle_sha256",
        "source_manifest_sha256", "realm_android_library_aar_sha256",
        "deployment_id", "deployment_repository", "publishing_type",
        "validation_state_trace", "runtime_provenance", "ci_artifact_sha256",
        "ci_run_id", "ci_artifact_id", "environment_policy_audit_sha256",
        "validated_deployment_mirror_evidence_sha256", "validated_mirror_url",
    )
    if any(key not in value for key in required):
        raise PortalError("prepared stage is incomplete")
    validate_release_binding(
        str(value["tag"]), str(value["version"]),
        str(value["commit"]), str(value["core_commit"]),
    )
    for field, label in (
        ("bundle_sha256", "bundle SHA-256"),
        ("source_manifest_sha256", "source manifest SHA-256"),
        ("realm_android_library_aar_sha256", "realm-android-library AAR SHA-256"),
        ("ci_artifact_sha256", "CI artifact SHA-256"),
        ("environment_policy_audit_sha256", "environment policy audit SHA-256"),
        ("validated_deployment_mirror_evidence_sha256", "validated mirror evidence SHA-256"),
    ):
        _require_sha256(value[field], label)
    _require_positive_decimal(value["ci_run_id"], "CI run ID")
    _require_positive_decimal(value["ci_artifact_id"], "CI artifact ID")
    deployment_id = str(value["deployment_id"])
    PortalClient._validate_deployment_id(deployment_id)
    if value["publishing_type"] != "USER_MANAGED":
        raise PortalError("prepared stage is not USER_MANAGED")
    expected_endpoint = (
        f"{PORTAL_URL}/api/v1/publisher/deployment/{deployment_id}/download/{{relative_path}}"
    )
    if value["deployment_repository"] != expected_endpoint:
        raise PortalError("invalid exact deployment repository")
    mirror_url = str(value["validated_mirror_url"])
    parsed = urlparse(mirror_url)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost") or parsed.query or parsed.fragment:
        raise PortalError("prepared stage has an invalid validated mirror URL")
    trace = value["validation_state_trace"]
    if (
        not isinstance(trace, list) or not trace or not isinstance(trace[-1], dict)
        or trace[-1].get("deployment_id") != deployment_id
        or trace[-1].get("state") != "VALIDATED"
    ):
        raise PortalError("prepared stage lacks a validated exact-deployment trace")
    provenance = value["runtime_provenance"]
    if not isinstance(provenance, dict):
        raise PortalError("prepared stage lacks runtime provenance")
    if provenance.get("head") != value["commit"] or provenance.get("core_commit") != value["core_commit"]:
        raise PortalError("prepared stage runtime provenance differs from source binding")
    return dict(value)


def _read_stage_prepared(path: Path, expected_sha256: str) -> dict[str, object]:
    return _validate_prepared_stage(
        _read_hashed_json(path, expected_sha256, label="prepared stage")
    )


def _verify_materialized_mirror(
    prepared: Mapping[str, object], evidence_root: Path
) -> None:
    evidence_path = evidence_root / "validated-deployment-mirror-evidence.json"
    if (
        not evidence_path.is_file()
        or sha256_file(evidence_path)
        != prepared["validated_deployment_mirror_evidence_sha256"]
    ):
        raise PortalError("validated mirror evidence SHA-256 mismatch")
    evidence = _read_json_object(evidence_path, "validated mirror evidence")
    if (
        evidence.get("format") != MIRROR_EVIDENCE_FORMAT
        or evidence.get("deployment_id") != prepared["deployment_id"]
        or evidence.get("deployment_repository") != prepared["deployment_repository"]
        or evidence.get("source_manifest_sha256") != prepared["source_manifest_sha256"]
    ):
        raise PortalError("validated mirror evidence differs from prepared stage")
    parsed = urlparse(str(prepared["validated_mirror_url"]))
    mirror = Path(unquote(parsed.path)).resolve()
    expected_mirror = (evidence_root / "validated-deployment-mirror").resolve()
    if mirror != expected_mirror or not mirror.is_dir():
        raise PortalError("validated mirror path differs from prepared stage evidence")
    files = evidence.get("files")
    if not isinstance(files, list) or not files:
        raise PortalError("validated mirror evidence has no files")
    expected_paths: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise PortalError("validated mirror file evidence is invalid")
        relative = str(item.get("path", ""))
        if not relative or any(part in {"", ".", ".."} for part in relative.split("/")):
            raise PortalError("validated mirror file path is invalid")
        expected_paths.add(relative)
        artifact = mirror.joinpath(*relative.split("/"))
        if not artifact.is_file() or sha256_file(artifact) != item.get("sha256"):
            raise PortalError("validated mirror artifact differs from evidence")
    actual_paths = {
        path.relative_to(mirror).as_posix() for path in mirror.rglob("*") if path.is_file()
    }
    if actual_paths != expected_paths:
        raise PortalError("validated mirror contains unexpected or missing artifacts")


def stage(
    *,
    bundle: Path,
    source_manifest: Path,
    tag: str,
    version: str,
    commit: str,
    core_commit: str,
    runtime_provenance: Path,
    ci_artifact_sha256: str,
    ci_run_id: str,
    ci_artifact_id: str,
    environment_policy_audit: Path,
    validated_mirror_evidence: Path,
    stage_prepared: Path,
    stage_manifest: Path,
    token_env: str,
    allow_network: bool,
    attempts: int,
    delay_seconds: float,
    backoff_factor: float = 1.5,
    max_delay_seconds: float = 60.0,
    deadline_seconds: float = 900.0,
    client: PortalClient | None = None,
    drop_failed_deployment: bool = False,
) -> Mapping[str, object]:
    """Upload/validate/download only; this token-bearing process never runs consumers."""

    validate_release_binding(tag, version, commit, core_commit)
    failure_path = stage_manifest.with_name(stage_manifest.name + ".failed.json")
    if stage_prepared.exists() or stage_manifest.exists() or failure_path.exists():
        raise PortalError("stage manifest already has an upload outcome")
    bundle_sha256, source_manifest_sha256 = verify_bundle_binding(bundle, source_manifest)
    realm_android_library_aar_sha256_value = realm_android_library_aar_sha256(bundle, version)
    provenance = verify_runtime_provenance(runtime_provenance, commit, core_commit)
    ci_artifact_sha256 = _require_sha256(ci_artifact_sha256, "CI artifact SHA-256")
    ci_run_id = _require_positive_decimal(ci_run_id, "CI run ID")
    ci_artifact_id = _require_positive_decimal(ci_artifact_id, "CI artifact ID")
    policy_audit_sha256 = verify_environment_policy_audit(environment_policy_audit)
    if not allow_network:
        raise PortalError("network access requires --allow-network")
    client = client or PortalClient(_token_from_environment(token_env))
    try:
        deployment_id = client.upload_user_managed(bundle, tag)
    except PortalError:
        _write_first_failure(
            stage_manifest, deployment_id="UNKNOWN", expected="UPLOAD_201", state="AMBIGUOUS",
            bundle_sha256=bundle_sha256, source_manifest_sha256=source_manifest_sha256,
            drop_failed_deployment=drop_failed_deployment,
        )
        raise
    try:
        client.poll(
            deployment_id, "VALIDATED", attempts=attempts,
            delay_seconds=delay_seconds, backoff_factor=backoff_factor,
            max_delay_seconds=max_delay_seconds, deadline_seconds=deadline_seconds,
        )
        repository_template = client.deployment_repository(deployment_id)
        repository_url, mirror_evidence_sha256 = _materialize_verified_deployment_mirror(
            client, deployment_id=deployment_id, source_manifest=source_manifest,
            evidence_root=validated_mirror_evidence,
        )
    except PortalError as error:
        state = (
            error.state if isinstance(error, DeploymentFailed)
            else str(client.last_poll_trace[-1]["state"])
            if client.last_poll_trace else "UNKNOWN"
        )
        _write_first_failure(
            stage_manifest, deployment_id=deployment_id,
            expected="VALIDATED_AND_VERIFIED_MIRROR", state=state,
            bundle_sha256=bundle_sha256, source_manifest_sha256=source_manifest_sha256,
            state_trace=client.last_poll_trace,
            drop_failed_deployment=drop_failed_deployment,
        )
        if drop_failed_deployment and state in {"FAILED", "VALIDATED"}:
            try:
                client.drop(deployment_id)
            except PortalError as drop_error:
                raise PortalError("stage failure evidence was preserved but deployment drop failed") from drop_error
        raise
    prepared: dict[str, object] = {
        "format": STAGE_PREPARED_FORMAT,
        "tag": tag,
        "version": version,
        "commit": commit,
        "core_commit": core_commit,
        "bundle_sha256": bundle_sha256,
        "source_manifest_sha256": source_manifest_sha256,
        "realm_android_library_aar_sha256": realm_android_library_aar_sha256_value,
        "runtime_provenance": provenance,
        "ci_artifact_sha256": ci_artifact_sha256,
        "ci_run_id": ci_run_id,
        "ci_artifact_id": ci_artifact_id,
        "environment_policy_audit_sha256": policy_audit_sha256,
        "validated_deployment_mirror_evidence_sha256": mirror_evidence_sha256,
        "validated_mirror_url": repository_url,
        "deployment_id": deployment_id,
        "publishing_type": "USER_MANAGED",
        "deployment_repository": repository_template,
        "validation_state_trace": client.last_poll_trace,
    }
    _validate_prepared_stage(prepared)
    _write_json(stage_prepared, prepared)
    return {
        "deployment_id": deployment_id,
        "stage_prepared_sha256": sha256_file(stage_prepared),
    }


def finalize_stage(
    *,
    stage_prepared: Path,
    stage_prepared_sha256: str,
    validated_consumer_command: Path,
    validated_consumer_gradle_home: Path,
    validated_consumer_evidence: Path,
    stage_manifest: Path,
    consumer_runner: ConsumerRunner | None = None,
) -> Mapping[str, object]:
    """Run the validated consumer only from a tokenless process and seal the stage manifest."""

    _assert_tokenless_process()
    failure_path = stage_manifest.with_name(stage_manifest.name + ".failed.json")
    if stage_manifest.exists() or failure_path.exists():
        raise PortalError("stage manifest already has a consumer outcome")
    prepared = _read_stage_prepared(stage_prepared, stage_prepared_sha256)
    _verify_materialized_mirror(prepared, validated_consumer_evidence)
    try:
        consumer_sha256 = _run_consumer(
            validated_consumer_command,
            repository_url=str(prepared["validated_mirror_url"]),
            mode="validated-mirror",
            token_env="CENTRAL_PORTAL_BEARER_TOKEN",
            gradle_user_home=validated_consumer_gradle_home,
            evidence=validated_consumer_evidence,
            runner=consumer_runner,
        )
    except PortalError:
        _write_first_failure(
            stage_manifest, deployment_id=str(prepared["deployment_id"]),
            expected="CONSUMER_PASS", state="VALIDATED",
            bundle_sha256=str(prepared["bundle_sha256"]),
            source_manifest_sha256=str(prepared["source_manifest_sha256"]),
            state_trace=prepared["validation_state_trace"],
            drop_failed_deployment=False,
        )
        raise
    manifest = dict(prepared)
    manifest["format"] = STAGE_MANIFEST_FORMAT
    manifest.pop("validated_mirror_url", None)
    manifest["validated_consumer_evidence_sha256"] = consumer_sha256
    _write_json(stage_manifest, manifest)
    stage_sha256 = sha256_file(stage_manifest)
    _read_stage_manifest(stage_manifest, stage_sha256)
    return {
        "deployment_id": manifest["deployment_id"],
        "stage_manifest_sha256": stage_sha256,
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
    deadline_seconds: float = 900.0,
    client: PortalClient | None = None,
    release_prepared: Path,
    release_evidence: Path | None = None,
) -> Mapping[str, object]:
    """Publish/poll only; the token-bearing process exits before public consumption."""

    if release_prepared.exists() or (release_evidence is not None and release_evidence.exists()):
        raise PortalError("release transaction already has an outcome")
    manifest = _read_stage_manifest(stage_manifest, stage_manifest_sha256)
    if not allow_network:
        raise PortalError("network access requires --allow-network")
    client = client or PortalClient(_token_from_environment(token_env))
    deployment_id = str(manifest["deployment_id"])
    publication_trace: list[dict[str, object]] = []
    try:
        state = client.deployment_status(deployment_id)
        publication_trace.append({"step": "initial-status", "state": state})
        if state != "VALIDATED":
            raise PortalError("exact deployment was published outside the approved release transaction")
        client.publish(deployment_id)
        publication_trace.append({"step": "publish-request", "state": "PUBLISHING"})
        client.poll(
            deployment_id, "PUBLISHED", attempts=attempts,
            delay_seconds=delay_seconds, backoff_factor=backoff_factor,
            max_delay_seconds=max_delay_seconds, deadline_seconds=deadline_seconds,
        )
        publication_trace.extend(client.last_poll_trace)
    except PortalError:
        if release_evidence is not None:
            _write_json(
                release_evidence,
                {
                    "format": "realm-maven-central-release-evidence-v1",
                    "deployment_id": deployment_id,
                    "stage_manifest_sha256": stage_manifest_sha256,
                    "result": "FAILED",
                    "publication_state_trace": publication_trace,
                },
            )
        raise
    prepared = {
        "format": RELEASE_PREPARED_FORMAT,
        "deployment_id": deployment_id,
        "stage_manifest_sha256": stage_manifest_sha256,
        "realm_android_library_aar_sha256": manifest["realm_android_library_aar_sha256"],
        "publication_state_trace": publication_trace,
        "state": "PUBLISHED",
    }
    _write_json(release_prepared, prepared)
    return {
        "deployment_id": deployment_id,
        "state": "PUBLISHED",
        "release_prepared_sha256": sha256_file(release_prepared),
        "publication_state_trace": publication_trace,
    }


def finalize_release(
    *,
    stage_manifest: Path,
    stage_manifest_sha256: str,
    release_prepared: Path,
    release_prepared_sha256: str,
    published_consumer_command: Path,
    published_consumer_gradle_home: Path,
    published_consumer_evidence: Path,
    consumer_runner: ConsumerRunner | None = None,
    release_evidence: Path,
) -> Mapping[str, object]:
    """Consume Maven Central in a separate tokenless process and seal release evidence."""

    _assert_tokenless_process()
    if release_evidence.exists():
        raise PortalError("release evidence already exists")
    manifest = _read_stage_manifest(stage_manifest, stage_manifest_sha256)
    prepared = _read_hashed_json(
        release_prepared, release_prepared_sha256, label="prepared release"
    )
    if (
        prepared.get("format") != RELEASE_PREPARED_FORMAT
        or prepared.get("deployment_id") != manifest["deployment_id"]
        or prepared.get("stage_manifest_sha256") != stage_manifest_sha256
        or prepared.get("realm_android_library_aar_sha256")
        != manifest["realm_android_library_aar_sha256"]
        or prepared.get("state") != "PUBLISHED"
    ):
        raise PortalError("prepared release differs from exact staged deployment")
    publication_trace = prepared.get("publication_state_trace")
    deployment_id = str(manifest["deployment_id"])
    if (
        not isinstance(publication_trace, list)
        or len(publication_trace) < 3
        or publication_trace[0] != {"step": "initial-status", "state": "VALIDATED"}
        or publication_trace[1] != {"step": "publish-request", "state": "PUBLISHING"}
    ):
        raise PortalError("prepared release lacks the ordered publication trace")
    poll_trace = publication_trace[2:]
    if (
        any(
            not isinstance(item, dict)
            or item.get("deployment_id") != deployment_id
            or item.get("state") not in {"VALIDATED", "PUBLISHING", "PUBLISHED"}
            for item in poll_trace
        )
        or poll_trace[-1].get("state") != "PUBLISHED"
        or any(item.get("state") == "PUBLISHED" for item in poll_trace[:-1])
    ):
        raise PortalError("prepared release lacks an exact final PUBLISHED deployment trace")
    try:
        consumer_sha256 = _run_consumer(
            published_consumer_command,
            repository_url="https://repo.maven.apache.org/maven2",
            mode="central",
            token_env="CENTRAL_PORTAL_BEARER_TOKEN",
            gradle_user_home=published_consumer_gradle_home,
            evidence=published_consumer_evidence,
            expected_realm_android_library_aar_sha256=str(
                manifest["realm_android_library_aar_sha256"]
            ),
            runner=consumer_runner,
        )
    except PortalError:
        _write_json(
            release_evidence,
            {
                "format": "realm-maven-central-release-evidence-v1",
                "deployment_id": manifest["deployment_id"],
                "stage_manifest_sha256": stage_manifest_sha256,
                "result": "FAILED",
                "publication_state_trace": publication_trace,
            },
        )
        raise
    result = {
        "deployment_id": manifest["deployment_id"],
        "state": "PUBLISHED",
        "published_consumer_evidence_sha256": consumer_sha256,
        "publication_state_trace": publication_trace,
    }
    _write_json(
        release_evidence,
        {
            "format": "realm-maven-central-release-evidence-v1",
            "deployment_id": manifest["deployment_id"],
            "stage_manifest_sha256": stage_manifest_sha256,
            "result": "PASS",
            "published_consumer_evidence_sha256": consumer_sha256,
            "publication_state_trace": publication_trace,
        },
    )
    result["release_evidence_sha256"] = sha256_file(release_evidence)
    return result

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

    verify_stage = commands.add_parser(
        "verify-stage-manifest", help="verify an immutable stage manifest without network"
    )
    verify_stage.add_argument("--stage-manifest", required=True, type=Path)
    verify_stage.add_argument("--stage-manifest-sha256", required=True)

    policy = commands.add_parser("audit-environment-policy", help="write a redacted, hashed environment-policy audit")
    policy.add_argument("--stage-policy", required=True, type=Path)
    policy.add_argument("--stage-deployment-policies", required=True, type=Path)
    policy.add_argument("--release-policy", required=True, type=Path)
    policy.add_argument("--release-deployment-policies", required=True, type=Path)
    policy.add_argument("--repository", required=True)
    policy.add_argument("--admin-bypass-attestation", type=Path)
    policy.add_argument("--gate-time", required=True)
    policy.add_argument("--release-tag", required=True)
    policy.add_argument("--audit-file", required=True, type=Path)

    stage_parser = commands.add_parser("stage", help="upload one USER_MANAGED deployment and wait for VALIDATED")
    stage_parser.add_argument("--bundle", required=True, type=Path)
    stage_parser.add_argument("--source-manifest", required=True, type=Path)
    stage_parser.add_argument("--tag", required=True)
    stage_parser.add_argument("--version", required=True)
    stage_parser.add_argument("--commit", required=True)
    stage_parser.add_argument("--core-commit", required=True)
    stage_parser.add_argument("--runtime-provenance", required=True, type=Path)
    stage_parser.add_argument("--ci-artifact-sha256", required=True)
    stage_parser.add_argument("--ci-run-id", required=True)
    stage_parser.add_argument("--ci-artifact-id", required=True)
    stage_parser.add_argument("--environment-policy-audit", required=True, type=Path)
    stage_parser.add_argument("--validated-mirror-evidence", required=True, type=Path)
    stage_parser.add_argument("--stage-prepared", required=True, type=Path)
    stage_parser.add_argument("--stage-manifest", required=True, type=Path)
    stage_parser.add_argument("--token-env", default="CENTRAL_PORTAL_TOKEN")
    stage_parser.add_argument("--poll-attempts", default=12, type=_positive_int)
    stage_parser.add_argument("--poll-delay-seconds", default=5.0, type=float)
    stage_parser.add_argument("--poll-backoff-factor", default=1.5, type=float)
    stage_parser.add_argument("--poll-max-delay-seconds", default=60.0, type=float)
    stage_parser.add_argument("--poll-deadline-seconds", default=900.0, type=float)
    stage_parser.add_argument("--allow-network", action="store_true")
    stage_parser.add_argument(
        "--drop-failed-deployment",
        action="store_true",
        help="after preserving evidence, drop a FAILED or VALIDATED unpublished deployment",
    )

    release_parser = commands.add_parser("release", help="publish the exact deployment in a staged manifest")
    release_parser.add_argument("--stage-manifest", required=True, type=Path)
    release_parser.add_argument("--stage-manifest-sha256", required=True)
    release_parser.add_argument("--release-prepared", required=True, type=Path)
    release_parser.add_argument("--release-evidence", required=True, type=Path)
    release_parser.add_argument("--token-env", default="CENTRAL_PORTAL_TOKEN")
    release_parser.add_argument("--poll-attempts", default=12, type=_positive_int)
    release_parser.add_argument("--poll-delay-seconds", default=5.0, type=float)
    release_parser.add_argument("--poll-backoff-factor", default=1.5, type=float)
    release_parser.add_argument("--poll-max-delay-seconds", default=60.0, type=float)
    release_parser.add_argument("--poll-deadline-seconds", default=900.0, type=float)
    release_parser.add_argument("--allow-network", action="store_true")

    finalize_stage_parser = commands.add_parser(
        "finalize-stage", help="run the validated consumer from a separate tokenless process"
    )
    finalize_stage_parser.add_argument("--stage-prepared", required=True, type=Path)
    finalize_stage_parser.add_argument("--stage-prepared-sha256", required=True)
    finalize_stage_parser.add_argument("--validated-consumer-command", required=True, type=Path)
    finalize_stage_parser.add_argument("--validated-consumer-gradle-home", required=True, type=Path)
    finalize_stage_parser.add_argument("--validated-consumer-evidence", required=True, type=Path)
    finalize_stage_parser.add_argument("--stage-manifest", required=True, type=Path)

    finalize_release_parser = commands.add_parser(
        "finalize-release", help="run the public consumer from a separate tokenless process"
    )
    finalize_release_parser.add_argument("--stage-manifest", required=True, type=Path)
    finalize_release_parser.add_argument("--stage-manifest-sha256", required=True)
    finalize_release_parser.add_argument("--release-prepared", required=True, type=Path)
    finalize_release_parser.add_argument("--release-prepared-sha256", required=True)
    finalize_release_parser.add_argument("--published-consumer-command", required=True, type=Path)
    finalize_release_parser.add_argument("--published-consumer-gradle-home", required=True, type=Path)
    finalize_release_parser.add_argument("--published-consumer-evidence", required=True, type=Path)
    finalize_release_parser.add_argument("--release-evidence", required=True, type=Path)
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
        elif args.command == "verify-stage-manifest":
            manifest = _read_stage_manifest(args.stage_manifest, args.stage_manifest_sha256)
            result = {
                "status": "VERIFIED",
                "deployment_id": manifest["deployment_id"],
                "stage_manifest_sha256": args.stage_manifest_sha256,
            }
        elif args.command == "audit-environment-policy":
            result = {
                "status": "VERIFIED",
                "environment_policy_audit_sha256": write_environment_policy_audit(
                    args.stage_policy,
                    args.stage_deployment_policies,
                    args.release_policy,
                    args.release_deployment_policies,
                    args.repository,
                    args.admin_bypass_attestation,
                    args.gate_time,
                    args.release_tag,
                    args.audit_file,
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
                ci_artifact_sha256=args.ci_artifact_sha256,
                ci_run_id=args.ci_run_id,
                ci_artifact_id=args.ci_artifact_id,
                environment_policy_audit=args.environment_policy_audit,
                validated_mirror_evidence=args.validated_mirror_evidence,
                stage_prepared=args.stage_prepared,
                stage_manifest=args.stage_manifest,
                token_env=args.token_env,
                allow_network=args.allow_network,
                attempts=args.poll_attempts,
                delay_seconds=args.poll_delay_seconds,
                backoff_factor=args.poll_backoff_factor,
                max_delay_seconds=args.poll_max_delay_seconds,
                deadline_seconds=args.poll_deadline_seconds,
                drop_failed_deployment=args.drop_failed_deployment,
            )
        elif args.command == "finalize-stage":
            result = finalize_stage(
                stage_prepared=args.stage_prepared,
                stage_prepared_sha256=args.stage_prepared_sha256,
                validated_consumer_command=args.validated_consumer_command,
                validated_consumer_gradle_home=args.validated_consumer_gradle_home,
                validated_consumer_evidence=args.validated_consumer_evidence,
                stage_manifest=args.stage_manifest,
            )
        elif args.command == "release":
            result = release(
                stage_manifest=args.stage_manifest,
                stage_manifest_sha256=args.stage_manifest_sha256,
                token_env=args.token_env,
                allow_network=args.allow_network,
                attempts=args.poll_attempts,
                delay_seconds=args.poll_delay_seconds,
                backoff_factor=args.poll_backoff_factor,
                max_delay_seconds=args.poll_max_delay_seconds,
                deadline_seconds=args.poll_deadline_seconds,
                release_prepared=args.release_prepared,
                release_evidence=args.release_evidence,
            )
        else:
            result = finalize_release(
                stage_manifest=args.stage_manifest,
                stage_manifest_sha256=args.stage_manifest_sha256,
                release_prepared=args.release_prepared,
                release_prepared_sha256=args.release_prepared_sha256,
                published_consumer_command=args.published_consumer_command,
                published_consumer_gradle_home=args.published_consumer_gradle_home,
                published_consumer_evidence=args.published_consumer_evidence,
                release_evidence=args.release_evidence,
            )
    except PortalError as error:
        print(f"central portal: FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
