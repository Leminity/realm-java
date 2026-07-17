#!/usr/bin/env python3
import os
import pathlib
import subprocess
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/g011-verify-native-elf.sh"
ABIS = ("armeabi-v7a", "arm64-v8a", "x86_64")


def make_aar(path: pathlib.Path, abis=ABIS):
    with zipfile.ZipFile(path, "w") as archive:
        for abi in abis:
            archive.writestr(f"jni/{abi}/librealm-jni.so", b"fixture")


def make_readelf(path: pathlib.Path):
    path.write_text("#!/usr/bin/env sh\nprintf 'Program Headers:\\n'\nprintf '  LOAD 0x0 0x0 0x0 0x10 0x10 R E %s\\n' \"${G011_TEST_ALIGN:-0x4000}\"\n")
    path.chmod(0o755)


class G011NativeElfTests(unittest.TestCase):
    def invoke(self, *args, env=None):
        environment = os.environ.copy()
        if env:
            environment.update(env)
        return subprocess.run([str(SCRIPT), *args], cwd=ROOT, env=environment, text=True, capture_output=True)

    def test_aar_pass_and_low_alignment_failure_have_checksummed_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            aar = tmp / "realm-android-library.aar"
            readelf = tmp / "llvm-readelf"
            make_aar(aar)
            make_readelf(readelf)
            passed = self.invoke("--aar", str(aar), "--llvm-readelf", str(readelf), "--evidence-dir", str(tmp / "pass"))
            self.assertEqual(passed.returncode, 0, passed.stderr)
            report = (tmp / "pass/report.txt").read_text()
            self.assertIn("ABI_SET=PASS", report)
            self.assertIn("RESULT=PASS", report)
            self.assertTrue((tmp / "pass/SHA256SUMS").is_file())
            checksum = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=tmp / "pass", text=True, capture_output=True)
            self.assertEqual(checksum.returncode, 0, checksum.stdout + checksum.stderr)
            failed = self.invoke("--aar", str(aar), "--llvm-readelf", str(readelf), "--evidence-dir", str(tmp / "fail"), env={"G011_TEST_ALIGN": "0x1000"})
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("RESULT=FAIL", (tmp / "fail/report.txt").read_text())
            self.assertTrue((tmp / "fail/checksum-verify.log").is_file())

    def test_bundle_and_forbidden_x86_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            aar = tmp / "realm-android-library.aar"
            readelf = tmp / "llvm-readelf"
            make_aar(aar)
            make_readelf(readelf)
            bundle = tmp / "bundle.zip"
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.write(aar, "io/github/leminity/realm/realm-android-library/10/realm-android-library-10.aar")
            bundled = self.invoke("--bundle", str(bundle), "--llvm-readelf", str(readelf), "--evidence-dir", str(tmp / "bundle"))
            self.assertEqual(bundled.returncode, 0, bundled.stderr)
            forbidden = tmp / "forbidden-x86.aar"
            make_aar(forbidden, (*ABIS, "x86"))
            result = self.invoke("--aar", str(forbidden), "--llvm-readelf", str(readelf), "--evidence-dir", str(tmp / "x86"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("x86 is forbidden", (tmp / "x86/report.txt").read_text())


    def test_rejects_nonempty_evidence_directory_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            aar = tmp / "realm-android-library.aar"
            readelf = tmp / "llvm-readelf"
            evidence = tmp / "evidence"
            make_aar(aar)
            make_readelf(readelf)
            evidence.mkdir()
            stale = evidence / "prior.txt"
            stale.write_text("do not replace")
            result = self.invoke("--aar", str(aar), "--llvm-readelf", str(readelf), "--evidence-dir", str(evidence))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(stale.read_text(), "do not replace")


if __name__ == "__main__":
    unittest.main()
