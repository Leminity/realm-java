#!/usr/bin/env python3
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/release.yml"


class G013DirectValidationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.runner = cls.workflow.split("cat > build/run-g011-consumer.sh <<'SH'", 1)[1].split("\n          SH", 1)[0]
        cls.central_runner = cls.workflow.split(
            "cat > build/run-g011-central-consumer.sh <<'SH'", 1
        )[1].split("\n          SH", 1)[0]

    def test_stage_consumer_uses_direct_validated_repository_and_bearer(self) -> None:
        self.assertIn('[[ "$mode" == validated', self.runner)
        self.assertIn("tools/g011-consume-six.sh --repository-url \"$url\" --mode validated", self.runner)
        self.assertIn('--bearer-env "$bearer_env"', self.runner)
        self.assertIn("ac08=(--mode validated --repository-url \"$url\"", self.runner)
        self.assertNotIn("--mode validated-mirror", self.runner)

    def test_consumer_evidence_binds_repository_by_hash_only(self) -> None:
        self.assertIn("'repository_url_sha256':hashlib.sha256(sys.argv[3].encode()).hexdigest()", self.runner)
        self.assertNotIn("'repository_url':sys.argv[3]", self.runner)

    def test_central_consumer_evidence_binds_repository_by_hash_only(self) -> None:
        self.assertIn(
            "'repository_url_sha256':hashlib.sha256(sys.argv[2].encode()).hexdigest()",
            self.central_runner,
        )
        self.assertNotIn("'repository_url':sys.argv[2]", self.central_runner)

    def test_portal_results_use_files_without_raw_tee(self) -> None:
        for result in (
            "build/maven-central-stage-portal-result.json",
            "build/maven-central-stage-result.json",
            "build/maven-central-release-portal-result.json",
            "build/maven-central-release-result.json",
        ):
            self.assertIn(f"--result-file {result}", self.workflow)
            self.assertNotIn(f"| tee {result}", self.workflow)

    def test_finalize_stage_passes_direct_consumer_bearer_contract(self) -> None:
        self.assertIn("--validated-consumer-bearer-env CENTRAL_PORTAL_BEARER_TOKEN", self.workflow)
        self.assertLess(
            self.workflow.index("tools/central-portal.py stage"),
            self.workflow.index("tools/central-portal.py finalize-stage"),
        )

    def test_recursive_scan_rejects_repository_and_deployment_identifiers(self) -> None:
        self.assertIn("repository_url = repository_template.removesuffix('/{relative_path}')", self.workflow)
        self.assertIn("deployment_id = prepared['deployment_id']", self.workflow)
        self.assertIn("validated repository identifier detected in retained evidence", self.workflow)

    def test_stage_scan_exempts_only_binding_manifests(self) -> None:
        scan = self.workflow.split(
            "      - name: Classify exact stage transaction evidence", 1
        )[0].rsplit("          protected = {", 1)[1]
        protected = scan.split("          for root_name", 1)[0]
        self.assertIn("prepared_path", protected)
        self.assertIn("maven-central-stage-manifest.json", protected)
        self.assertNotIn("maven-central-stage-manifest.json.failed.json", protected)
        self.assertNotIn("validated-deployment-mirror-evidence.json", protected)

    def test_release_scan_does_not_exempt_retained_release_evidence(self) -> None:
        scan = self.workflow.split(
            "      - name: Verify retained release evidence contains no credential material", 1
        )[1].split("      - name: Classify exact publication transaction evidence", 1)[0]
        protected = scan.split("          protected = {", 1)[1].split(
            "          for root_name", 1
        )[0]
        self.assertIn("maven-central-release-intent.json", protected)
        self.assertIn("maven-central-release-prepared.json", protected)
        self.assertNotIn("maven-central-release-evidence.json", protected)


if __name__ == "__main__":
    unittest.main()
