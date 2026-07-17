#!/usr/bin/env python3
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "compatibility-fixtures/ac08-api37-ps16k-runtime"
SCRIPT = FIXTURE / "run-ac08.sh"


class Ac08G011ParameterizationTests(unittest.TestCase):
    def run_script(self, *args, env=None):
        environment = os.environ.copy()
        if env:
            environment.update(env)
        return subprocess.run([str(SCRIPT), *args], cwd=ROOT, env=environment, text=True, capture_output=True)

    def test_validated_dry_run_redacts_and_keeps_remote_build_online(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            secret = "ac08-bearer-must-not-appear"
            result = self.run_script(
                "--mode", "validated",
                "--repository-url", "https://central.example/api/v1/publisher/deployment/deploy-123/download",
                "--bearer-env", "AC08_TEST_TOKEN",
                "--sdk-root", "/not-used-by-dry-run",
                "--serial", "emulator-5554",
                "--expected-avd", "realm-api37-ps16k-kvm",
                "--official-gradle", "/not-used-by-dry-run/gradle",
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
            self.assertNotIn("--offline", plan)
            self.assertNotIn(secret, all_text)
            self.assertTrue((evidence / "SHA256SUMS").is_file())

    def test_rejects_4k_or_lower_api_and_central_custom_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            common = ["--mode", "central", "--gradle-user-home", str(tmp / "home"), "--evidence-dir", str(tmp / "evidence"), "--dry-run"]
            rejected_identity = self.run_script(*common, "--dry-run-identity", "36,4096,realm-api37-ps16k-kvm,fatal,true")
            self.assertNotEqual(rejected_identity.returncode, 0)
            rejected_url = self.run_script(*common, "--repository-url", "https://central.example/deployment/x/download")
            self.assertNotEqual(rejected_url.returncode, 0)

    def test_gradle_routing_is_exclusive_in_all_resolution_paths(self):
        build = (FIXTURE / "build.gradle").read_text()
        settings = (FIXTURE / "settings.gradle").read_text()
        for text in (build, settings):
            self.assertIn("includeGroup('io.github.leminity.realm')", text)
            self.assertIn("excludeGroup('io.github.leminity.realm')", text)
            self.assertIn("HttpHeaderCredentials", text)
            self.assertIn("mavenCentral { content { includeGroup('io.github.leminity.realm') } }", text)
        self.assertIn("gradlePluginPortal { content { excludeGroup('io.github.leminity.realm') } }", settings)


if __name__ == "__main__":
    unittest.main()
