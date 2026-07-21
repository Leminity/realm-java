#!/usr/bin/env python3
import os
import pathlib
import subprocess
import tempfile
import hashlib
import tarfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "compatibility-fixtures/ac08-api37-ps16k-runtime"
SCRIPT = FIXTURE / "run-ac08.sh"


class Ac08G011ParameterizationTests(unittest.TestCase):
    OFFICIAL_ARCHIVE_ARGS = (
        "--official-gradle-home-archive", "/not-used-by-dry-run/official-home.tar.gz",
        "--official-gradle-home-archive-sha256", "a" * 64,
    )
    def run_script(self, *args, env=None):
        environment = os.environ.copy()
        if env:
            environment.update(env)
        return subprocess.run([str(SCRIPT), *args], cwd=ROOT, env=environment, text=True, capture_output=True)

    def test_validated_dry_run_redacts_and_keeps_remote_build_online(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            secret = "ac08-bearer-must-not-appear"
            repository_url = "https://central.example/api/v1/publisher/deployment/deploy-123/download"
            result = self.run_script(
                "--mode", "validated",
                "--repository-url", repository_url,
                "--bearer-env", "AC08_TEST_TOKEN",
                "--sdk-root", "/not-used-by-dry-run",
                "--serial", "emulator-5554",
                "--expected-avd", "realm-api37-ps16k-kvm",
                "--official-gradle", "/not-used-by-dry-run/gradle",
                *self.OFFICIAL_ARCHIVE_ARGS,
                "--immutable-encrypted", "/not-used-by-dry-run/input.realm",
                "--gradle-user-home", str(tmp / "home"),
                "--evidence-dir", str(tmp / "evidence"),
                "--run-id", "validated",
                "--dry-run", "--dry-run-identity", "37,16384,realm-api37-ps16k-kvm,fatal,true",
                env={"AC08_TEST_TOKEN": secret},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = tmp / "evidence/validated"
            plan = (evidence / "dry-run-command-plan.txt").read_text()
            all_text = "\n".join(path.read_text(errors="replace") for path in evidence.rglob("*") if path.is_file())
            self.assertIn("G011_FORK_BEARER=<redacted>", plan)
            fork_plan = next(line for line in plan.splitlines() if line.startswith("fork_build_command="))
            self.assertNotIn("--offline", fork_plan)
            self.assertIn("--offline", next(line for line in plan.splitlines() if line.startswith("official_build_command=")))
            self.assertIn("<redacted-validated-repository>", all_text)
            self.assertNotIn(repository_url, all_text)
            self.assertNotIn("deploy-123", all_text)
            self.assertNotIn(secret, all_text)
            self.assertTrue((evidence / "SHA256SUMS").is_file())
            checksum = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=evidence, text=True, capture_output=True)
            self.assertEqual(checksum.returncode, 0, checksum.stdout + checksum.stderr)

    def test_rejects_4k_or_lower_api_and_central_custom_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            common = ["--mode", "central", *self.OFFICIAL_ARCHIVE_ARGS, "--gradle-user-home", str(tmp / "home"), "--evidence-dir", str(tmp / "evidence"), "--dry-run"]
            rejected_identity = self.run_script(*common, "--dry-run-identity", "36,4096,realm-api37-ps16k-kvm,fatal,true")
            self.assertNotEqual(rejected_identity.returncode, 0)
            rejected_url = self.run_script(*common, "--repository-url", "https://central.example/deployment/x/download")
            self.assertNotEqual(rejected_url.returncode, 0)

    def test_validated_mirror_dry_run_is_tokenless_and_online_for_external_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            repository = tmp / "mirror"
            repository.mkdir()
            result = self.run_script(
                "--mode", "validated-mirror",
                "--repository-url", repository.resolve().as_uri(),
                "--sdk-root", "/not-used-by-dry-run",
                "--official-gradle", "/not-used-by-dry-run/gradle",
                *self.OFFICIAL_ARCHIVE_ARGS,
                "--immutable-encrypted", "/not-used-by-dry-run/input.realm",
                "--gradle-user-home", str(tmp / "home"),
                "--evidence-dir", str(tmp / "evidence"),
                "--run-id", "validated-mirror",
                "--dry-run", "--dry-run-identity", "37,16384,realm-api37-ps16k-kvm,fatal,true",
                env={"CENTRAL_PORTAL_BEARER_TOKEN": "must-not-be-used"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = (tmp / "evidence/validated-mirror/dry-run-command-plan.txt").read_text()
            self.assertIn("G011_REPOSITORY_MODE=validated-mirror", plan)
            self.assertNotIn("G011_FORK_BEARER", plan)
            fork_plan = next(line for line in plan.splitlines() if line.startswith("fork_build_command="))
            self.assertNotIn("--offline", fork_plan)
            self.assertIn("official_and_fork_gradle_homes=SEPARATE", plan)
            self.assertIn("extracted-checksum-bound-official-home", plan)
            metadata = (tmp / "evidence/validated-mirror/run-metadata.txt").read_text()
            self.assertIn(f"official_gradle_home_archive_sha256={'a' * 64}", metadata)

    def test_gradle_routing_is_exclusive_in_all_resolution_paths(self):
        build = (FIXTURE / "build.gradle").read_text()
        settings = (FIXTURE / "settings.gradle").read_text()
        for text in (build, settings):
            self.assertIn("includeGroup('io.github.leminity.realm')", text)
            self.assertIn("excludeGroup('io.github.leminity.realm')", text)
            self.assertIn("HttpHeaderCredentials", text)
            self.assertIn("mavenCentral { content { includeGroup('io.github.leminity.realm') } }", text)
        self.assertIn("gradlePluginPortal { content { excludeGroup('io.github.leminity.realm') } }", settings)

    def test_official_input_preflight_verifies_archive_fixture_and_offline_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            sdk = tmp / "sdk"
            aapt2 = sdk / "build-tools/36.0.0/aapt2"
            aapt2.parent.mkdir(parents=True)
            aapt2.write_text("#!/bin/sh\nexit 0\n")
            aapt2.chmod(0o755)
            gradle = tmp / "gradle-7.5"
            gradle.write_text(
                "#!/bin/sh\n"
                "case \" $* \" in *' --version '*) echo 'Gradle 7.5';; esac\n"
                "exit 0\n"
            )
            gradle.chmod(0o755)
            archive_source = tmp / "archive-source"
            (archive_source / "caches").mkdir(parents=True)
            (archive_source / "caches/marker").write_text("prewarmed")
            archive = tmp / "official-home.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                output.add(archive_source / "caches", arcname="caches")
            archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            immutable = (
                ROOT
                / "compatibility-fixtures/official-10.19.0-generator/generated/official-10.19.0-oracle/official-10.19.0-encrypted.realm"
            )
            result = self.run_script(
                "--sdk-root", str(sdk),
                "--official-gradle", str(gradle),
                "--official-gradle-home-archive", str(archive),
                "--official-gradle-home-archive-sha256", archive_sha,
                "--immutable-encrypted", str(immutable),
                "--official-inputs-preflight-only",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("AC08_OFFICIAL_INPUTS_PREFLIGHT=PASS", result.stdout)

            rejected = self.run_script(
                "--sdk-root", str(sdk),
                "--official-gradle", str(gradle),
                "--official-gradle-home-archive", str(archive),
                "--official-gradle-home-archive-sha256", "0" * 64,
                "--immutable-encrypted", str(immutable),
                "--official-inputs-preflight-only",
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("archive SHA-256 mismatch", rejected.stderr)


    def test_rejects_nonempty_run_id_evidence_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            evidence_root = tmp / "evidence"
            collision = evidence_root / "reused-run"
            collision.mkdir(parents=True)
            stale = collision / "prior.log"
            stale.write_text("keep")
            result = self.run_script(
                "--mode", "central", *self.OFFICIAL_ARCHIVE_ARGS, "--gradle-user-home", str(tmp / "home"),
                "--evidence-dir", str(evidence_root), "--run-id", "reused-run", "--dry-run",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(stale.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
