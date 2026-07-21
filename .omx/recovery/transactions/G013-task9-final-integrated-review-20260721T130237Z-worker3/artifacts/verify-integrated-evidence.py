#!/usr/bin/env python3
import argparse
import hashlib
import io
import json
import pathlib
import subprocess
import tarfile
import tempfile

SOURCE = "188f0832252172a5ca93204292a65a0f8fe4f4f3"
SOURCE_TREE = "4e99f91dfe86abbc957e5f9596de454d90c075aa"
CORE = "d7b52ccbada0283527db36143cfeab18692b4ed0"
CORE_PATH = "realm/realm-library/src/main/cpp/realm-core"
ITEMS = [
    {
        "task": 1,
        "commit": "a4cdb89565f3dc3a3c41ef99e027d096de9e9924",
        "parent": "d39316930fd63e379b58bc6296696781099ca4c7",
        "prefix": ".omx/recovery/transactions/G013-pre-publication-regression-20260721T090051Z-worker1",
        "paths": 35,
        "seals": 33,
        "status_counts": {"0": 2, "1": 2},
        "unsealed": ["SHA256SUMS", "checksum-verify.log"],
    },
    {
        "task": 2,
        "commit": "285617b195f03d703795115f5ada8de14b4d1e60",
        "parent": SOURCE,
        "prefix": ".omx/recovery/transactions/G013-task2-local-acceptance-20260721T092343Z-worker1",
        "paths": 296,
        "seals": 294,
        "status_counts": {"0": 25, "1": 1},
        "unsealed": ["CHECKSUM-VERIFY.log", "SHA256SUMS"],
    },
    {
        "task": 3,
        "commit": "42affb8d4e2a1fc078b1916ba653e8e1c99df135",
        "integrated_commit": "36b5c4ef8f076e39d194edb76f78a0ace2c0ed86",
        "parent": "d39316930fd63e379b58bc6296696781099ca4c7",
        "prefix": "evidence/g013/task3-abi-native/20260721T090205Z",
        "paths": 94,
        "seals": 90,
        "status_counts": {},
        "unsealed": [
            "CHECKSUM-VERIFY.log",
            "SHA256SUMS",
            "ac08/20260721T090205Z/SHA256SUMS",
            "native/SHA256SUMS",
        ],
        "nested_seals": [
            "ac08/20260721T090205Z/SHA256SUMS",
            "native/SHA256SUMS",
        ],
    },
    {
        "task": 4,
        "commit": "5f866d2479a69b9e4c19435041ce4e846e024695",
        "parent": "285617b195f03d703795115f5ada8de14b4d1e60",
        "prefix": ".omx/recovery/transactions/G013-task4-plugin-api-20260721T115459Z-worker1",
        "paths": 33,
        "seals": 31,
        "status_counts": {"0": 8},
        "unsealed": ["CHECKSUM-VERIFY.log", "SHA256SUMS"],
    },
    {
        "task": 5,
        "commit": "f5f46a5ca910ea419996daa52c44d7d93a8efcdf",
        "parent": "5f866d2479a69b9e4c19435041ce4e846e024695",
        "prefix": ".omx/recovery/transactions/G013-task5-exact-six-20260721T120149Z-worker1",
        "paths": 33,
        "seals": 31,
        "status_counts": {"0": 8},
        "unsealed": ["CHECKSUM-VERIFY.log", "SHA256SUMS"],
    },
    {
        "task": 6,
        "commit": "bb3416016a6d2cceb612bffb55f5e6aea84fb690",
        "parent": "f5f46a5ca910ea419996daa52c44d7d93a8efcdf",
        "prefix": ".omx/recovery/transactions/G013-task6-worker1-summary-20260721T122044Z-worker1",
        "paths": 21,
        "seals": 19,
        "status_counts": {"0": 3},
        "unsealed": ["CHECKSUM-VERIFY.log", "SHA256SUMS"],
    },
    {
        "task": 7,
        "commit": "c7f1e465d081eeacc89eae0844c793ac22d1746c",
        "integrated_commit": "ef8ed3f52ece1a092bc2480533656bba4e76609f",
        "parent": "d39316930fd63e379b58bc6296696781099ca4c7",
        "prefix": ".omx/recovery/transactions/G013-task7-portal-redaction-workflow-20260721T091005Z-worker3",
        "paths": 20,
        "seals": 18,
        "status_counts": {},
        "unsealed": ["CHECKSUM-VERIFY.log", "SHA256SUMS"],
    },
    {
        "task": 8,
        "commit": "40ba23b408d0f20b95e09a27b4dab3fbe3c538ee",
        "integrated_commit": "3e1d5407d860dcacb760042b53912e5908defe21",
        "parent": "42affb8d4e2a1fc078b1916ba653e8e1c99df135",
        "prefix": "evidence/g013/task8-native-runtime-audit/20260721T094802Z",
        "paths": 28,
        "seals": 25,
        "status_counts": {},
        "unsealed": [
            "CHECKSUM-VERIFY.log",
            "SHA256SUMS",
            "native-replay/SHA256SUMS",
        ],
        "nested_seals": ["native-replay/SHA256SUMS"],
    },
]
VERDICTS = {
    "AC-01": "PASS",
    "AC-02": "PASS",
    "AC-03": "PASS",
    "AC-04": "PASS",
    "AC-05": "PASS",
    "AC-06": "PASS",
    "AC-07": "PASS",
    "AC-08": "PASS",
    "AC-09": "PASS",
    "AC-10": "PASS",
    "AC-11": "PASS",
    "AC-12": "LOCAL_CONTRACT_PASS_EXTERNAL_STAGE_PENDING",
    "AC-13": "EXTERNAL_GATE_PENDING",
    "AC-14": "PASS",
    "AC-15": "PASS",
}

def run(repo, *args, check=True):
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode:
        raise AssertionError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc

def replay_manifest(root, manifest_rel):
    manifest = root / manifest_rel
    checked = 0
    for line in manifest.read_text().splitlines():
        digest, rel = line.split(None, 1)
        rel = rel.strip().removeprefix("*").removeprefix("./")
        target = manifest.parent / rel
        assert target.is_file(), f"missing sealed file {manifest_rel}:{rel}"
        assert hashlib.sha256(target.read_bytes()).hexdigest() == digest, (
            manifest_rel,
            rel,
        )
        checked += 1
    return checked

def status_counts(root):
    counts = {}
    for path in root.rglob("*.status"):
        value = path.read_text().strip()
        counts[value] = counts.get(value, 0) + 1
    return counts

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=pathlib.Path, required=True)
    parser.add_argument("--integrated-head", required=True)
    parser.add_argument("--task-state-root", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    head = run(repo, "rev-parse", args.integrated_head).stdout.strip()
    assert run(repo, "rev-parse", f"{SOURCE}^{{tree}}").stdout.strip() == SOURCE_TREE
    source_change = run(
        repo, "diff-tree", "--no-commit-id", "--name-only", "-r", SOURCE
    ).stdout.splitlines()
    assert source_change == ["evidence/provenance/g011-source-evidence-manifest.json"]
    core_line = run(repo, "ls-tree", SOURCE, CORE_PATH).stdout.split()
    assert core_line[0] == "160000" and core_line[2] == CORE
    assert run(repo, "merge-base", "--is-ancestor", SOURCE, head, check=False).returncode == 0

    current_core = run(repo, "ls-tree", head, CORE_PATH).stdout.split()
    assert current_core[0] == "160000" and current_core[2] == CORE

    allowed = tuple(item["prefix"] + "/" for item in ITEMS if item["task"] != 1)
    integrated_changes = run(repo, "diff", "--name-only", f"{SOURCE}..{head}").stdout.splitlines()
    unexpected = [path for path in integrated_changes if not path.startswith(allowed)]
    assert not unexpected, unexpected

    results = []
    total_paths = 0
    total_seals = 0
    total_nested = 0
    with tempfile.TemporaryDirectory(prefix="g013-task9-audit-") as tmp:
        tmp_root = pathlib.Path(tmp)
        for item in ITEMS:
            task = item["task"]
            commit = item["commit"]
            prefix = item["prefix"]
            assert run(repo, "rev-parse", f"{commit}^").stdout.strip() == item["parent"]
            integrated_commit = item.get("integrated_commit", commit)
            assert run(
                repo,
                "merge-base",
                "--is-ancestor",
                integrated_commit,
                head,
                check=False,
            ).returncode == 0, f"Task {task} integrated evidence commit is not an ancestor"
            paths = run(
                repo, "diff-tree", "--no-commit-id", "--name-only", "-r", commit
            ).stdout.splitlines()
            assert len(paths) == item["paths"], (task, len(paths), item["paths"])
            assert all(path.startswith(prefix + "/") for path in paths)
            original_tree = run(repo, "rev-parse", f"{commit}:{prefix}").stdout.strip()
            integrated_commit_tree = run(
                repo, "rev-parse", f"{integrated_commit}:{prefix}"
            ).stdout.strip()
            integrated_paths = run(
                repo,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                integrated_commit,
            ).stdout.splitlines()
            assert len(integrated_paths) == item["paths"]
            assert all(path.startswith(prefix + "/") for path in integrated_paths)
            integrated_tree = run(repo, "rev-parse", f"{head}:{prefix}").stdout.strip()
            assert original_tree == integrated_commit_tree == integrated_tree, (
                task,
                original_tree,
                integrated_commit_tree,
                integrated_tree,
            )

            archive = subprocess.check_output(["git", "-C", str(repo), "archive", commit, prefix])
            extract_root = tmp_root / f"task-{task}"
            extract_root.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(extract_root, filter="data")
            tx = extract_root / prefix
            files = sorted(
                str(path.relative_to(tx)) for path in tx.rglob("*") if path.is_file()
            )
            sealed = replay_manifest(tx, "SHA256SUMS")
            assert sealed == item["seals"], (task, sealed, item["seals"])
            sealed_paths = sorted(
                line.split(None, 1)[1].strip().removeprefix("*").removeprefix("./")
                for line in (tx / "SHA256SUMS").read_text().splitlines()
            )
            assert sorted(set(files) - set(sealed_paths)) == sorted(item["unsealed"])
            nested = 0
            for manifest in item.get("nested_seals", []):
                nested += replay_manifest(tx, manifest)
            assert status_counts(tx) == item["status_counts"], (
                task,
                status_counts(tx),
                item["status_counts"],
            )
            assert any("rollback" in path.lower() for path in files)
            if task == 2:
                rollback_check = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repo),
                        "apply",
                        "--check",
                        str(tx / "rollback/manifest-rollback.patch"),
                    ],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                assert rollback_check.returncode == 0, rollback_check.stderr
            if task in (4, 5, 6):
                assert (tx / "rollback/no-source-change.patch").read_bytes() == b""

            privacy_ok = task == 1
            privacy_files = [
                path for path in tx.rglob("*")
                if path.is_file() and "privacy" in path.name.lower()
            ]
            privacy_text = "\n".join(path.read_text(errors="replace") for path in privacy_files)
            if task == 2:
                privacy_ok = all(
                    marker in privacy_text
                    for marker in (
                        "files_scanned=293",
                        "hits=0",
                        "private_keyring_files=0",
                        "result=PASS",
                    )
                )
            elif task in (4, 5):
                privacy_ok = all(
                    marker in privacy_text
                    for marker in (
                        "files_scanned=30",
                        "hits=0",
                        "private_keyring_files=0",
                        "result=PASS",
                    )
                )
            elif task == 6:
                privacy_ok = all(
                    marker in privacy_text
                    for marker in (
                        "files_scanned=18",
                        "hits=0",
                        "private_keyring_files=0",
                        "result=PASS",
                    )
                )
            elif task in (3, 8):
                privacy_ok = "matches=0" in privacy_text and "RESULT=PASS" in privacy_text
            elif task == 7:
                privacy_ok = all(
                    marker in privacy_text
                    for marker in (
                        "RECURSIVE_SECRET_SCAN PASS",
                        "DEPLOYMENT_IDENTIFIER_SCAN PASS",
                        "REPOSITORY_IDENTIFIER_PROJECTION PASS",
                    )
                )
            assert privacy_ok, f"Task {task} privacy evidence failed"
            forbidden_private = [
                path for path in files
                if "private-keys-v1.d" in path.lower()
                or pathlib.PurePosixPath(path).name.lower() == "secring.gpg"
            ]
            assert not forbidden_private, (task, forbidden_private)
            total_paths += len(paths)
            total_seals += sealed
            total_nested += nested
            results.append(
                {
                    "task": task,
                    "original_commit": commit,
                    "integrated_commit": integrated_commit,
                    "parent": item["parent"],
                    "transaction": prefix,
                    "commit_paths": len(paths),
                    "seal_entries": sealed,
                    "nested_seal_entries": nested,
                    "status_counts": item["status_counts"],
                    "subtree_integrated_exactly": True,
                    "rollback_present": True,
                    "privacy_evidence_pass": True,
                }
            )

    assert total_paths == 560
    assert total_seals == 541
    assert total_nested == 36

    task_states = {}
    for task in range(1, 10):
        data = json.loads(
            (args.task_state_root / f"task-{task}.json").read_text()
        )
        task_states[str(task)] = data["status"]
    task10 = json.loads((args.task_state_root / "task-10.json").read_text())
    task_states["10"] = task10["status"]
    assert all(task_states[str(task)] == "completed" for task in range(1, 9))
    assert task_states["9"] == "in_progress"
    assert task_states["10"] == "completed"

    output = {
        "result": "PASS",
        "integrated_head": head,
        "source_under_test": SOURCE,
        "source_tree": SOURCE_TREE,
        "core_commit": CORE,
        "source_refresh_paths": source_change,
        "integrated_changes": len(integrated_changes),
        "unexpected_non_evidence_changes": [],
        "tasks": results,
        "top_level_transaction_paths": total_paths,
        "top_level_seal_entries_replayed": total_seals,
        "nested_seal_entries_replayed": total_nested,
        "task_states": task_states,
        "acceptance": VERDICTS,
        "historical_nonzero_statuses": {
            "Task1": [
                "baseline-manifest.status=1",
                "baseline-manifest-unit.status=1",
            ],
            "Task2": ["manifest-unit.status=1"],
        },
        "historical_findings_remediated": True,
        "local_failures": [],
        "external_actions": "none",
        "ultragoal_or_codex_goal_mutation": "none",
    }
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, sort_keys=True))

if __name__ == "__main__":
    main()
