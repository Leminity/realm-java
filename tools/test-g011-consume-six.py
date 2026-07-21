#!/usr/bin/env python3
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/g011-consume-six.sh"


class G011ConsumeSixTests(unittest.TestCase):
    def run_script(self, *args, env=None):
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        return subprocess.run([str(SCRIPT), *args], cwd=ROOT, env=run_env, text=True, capture_output=True)

    def test_validated_dry_run_redacts_secret_and_routes_exclusively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            evidence = root / "evidence"
            home = root / "home"
            secret = "do-not-write-this-bearer"
            repository_url = "https://central.example/api/v1/publisher/deployment/deploy-123/download"
            result = self.run_script(
                "--mode", "validated",
                "--repository-url", repository_url,
                "--bearer-env", "G011_TEST_BEARER",
                "--gradle-user-home", str(home),
                "--evidence-dir", str(evidence),
                "--dry-run",
                env={"G011_TEST_BEARER": secret},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            settings = (evidence / "settings.gradle.redacted").read_text()
            command = (evidence / "command.redacted.txt").read_text()
            self.assertIn("HttpHeaderCredentials", settings)
            self.assertIn("excludeGroup('io.github.leminity.realm')", settings)
            self.assertIn("gradlePluginPortal", settings)
            self.assertIn("G011_FORK_BEARER=<redacted>", command)
            all_text = "\n".join(p.read_text(errors="replace") for p in evidence.rglob("*") if p.is_file())
            self.assertIn("<redacted-validated-repository>", all_text)
            self.assertNotIn(repository_url, all_text)
            self.assertNotIn("deploy-123", all_text)
            self.assertNotIn(secret, all_text)
            self.assertTrue((evidence / "SHA256SUMS").is_file())
            self.assertTrue((evidence / "checksum-verify.log").is_file())
            checksum = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=evidence, text=True, capture_output=True)
            self.assertEqual(checksum.returncode, 0, checksum.stdout + checksum.stderr)

    def test_validated_rejects_missing_secret_and_non_deployment_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            missing = self.run_script(
                "--mode", "validated", "--repository-url", "https://central.example/deployment/x/download",
                "--bearer-env", "MISSING", "--gradle-user-home", str(root / "home"),
                "--evidence-dir", str(root / "evidence"), "--dry-run",
            )
            self.assertNotEqual(missing.returncode, 0)
            invalid = self.run_script(
                "--mode", "validated", "--repository-url", "https://central.example/releases/x",
                "--bearer-env", "TOKEN", "--gradle-user-home", str(root / "home2"),
                "--evidence-dir", str(root / "evidence2"), "--dry-run", env={"TOKEN": "value"},
            )
            self.assertNotEqual(invalid.returncode, 0)

    def test_validated_mirror_is_file_only_tokenless_and_online_for_external_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repository = root / "validated-mirror"
            repository.mkdir()
            evidence = root / "evidence"
            result = self.run_script(
                "--mode", "validated-mirror",
                "--repository-url", repository.resolve().as_uri(),
                "--gradle-user-home", str(root / "home"),
                "--evidence-dir", str(evidence),
                "--dry-run",
                env={"CENTRAL_PORTAL_BEARER_TOKEN": "must-not-be-used"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            settings = (evidence / "settings.gradle.redacted").read_text()
            command = (evidence / "command.redacted.txt").read_text()
            self.assertIn("G011_REPOSITORY_MODE') == 'validated'", settings)
            self.assertNotIn("G011_FORK_BEARER", command)
            self.assertNotIn("--offline", command)
            self.assertIn(repository.resolve().as_uri(), command)
            rejected = self.run_script(
                "--mode", "validated-mirror",
                "--repository-url", "https://central.example/deployment/x/download",
                "--gradle-user-home", str(root / "home2"),
                "--evidence-dir", str(root / "evidence2"),
                "--dry-run",
            )
            self.assertNotEqual(rejected.returncode, 0)

    def test_local_empty_cache_allows_only_external_dependencies_from_public_repositories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repository = root / "fork-repository"
            repository.mkdir()
            evidence = root / "evidence"
            result = self.run_script(
                "--mode", "local",
                "--repository", str(repository),
                "--gradle-user-home", str(root / "empty-home"),
                "--evidence-dir", str(evidence),
                "--dry-run",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            command = (evidence / "command.redacted.txt").read_text()
            settings = (evidence / "settings.gradle.redacted").read_text()
            self.assertNotIn("--offline", command)
            self.assertIn("includeGroup('io.github.leminity.realm')", settings)
            self.assertEqual(settings.count("google { content { excludeGroup('io.github.leminity.realm') } }"), 2)
            self.assertEqual(settings.count("mavenCentral { content { excludeGroup('io.github.leminity.realm') } }"), 2)
            self.assertIn("gradlePluginPortal { content { excludeGroup('io.github.leminity.realm') } }", settings)
            self.assertNotIn("mavenLocal", settings)
            self.assertNotIn("jitpack", settings.lower())

    def test_central_rejects_custom_url_and_has_no_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            result = self.run_script(
                "--mode", "central", "--repository-url", "https://central.example/deployment/x/download",
                "--gradle-user-home", str(root / "home"), "--evidence-dir", str(root / "evidence"), "--dry-run",
            )
            self.assertNotEqual(result.returncode, 0)
            passing = self.run_script(
                "--mode", "central", "--gradle-user-home", str(root / "home2"),
                "--evidence-dir", str(root / "evidence2"), "--dry-run",
            )
            self.assertEqual(passing.returncode, 0, passing.stderr)
            settings = (root / "evidence2/settings.gradle.redacted").read_text()
            self.assertIn("mavenCentral { content { includeGroup('io.github.leminity.realm') } }", settings)


    def test_rejects_nonempty_evidence_directory_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            evidence = root / "evidence"
            evidence.mkdir()
            stale = evidence / "stale.txt"
            stale.write_text("preserve me")
            result = self.run_script(
                "--mode", "central", "--gradle-user-home", str(root / "home"),
                "--evidence-dir", str(evidence), "--dry-run",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(stale.read_text(), "preserve me")


if __name__ == "__main__":
    unittest.main()
