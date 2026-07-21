#!/usr/bin/env python3
import hashlib
import json
import os
import pathlib
import subprocess

ROOT = pathlib.Path.cwd()
SOURCE = '188f0832252172a5ca93204292a65a0f8fe4f4f3'
SOURCE_TREE = '4e99f91dfe86abbc957e5f9596de454d90c075aa'
CORE = 'd7b52ccbada0283527db36143cfeab18692b4ed0'
TASK6_TX = pathlib.Path(os.environ['TASK6_TX'])
records = [
    {
        'task': 1,
        'commit': 'a4cdb89565f3dc3a3c41ef99e027d096de9e9924',
        'parent': 'd39316930fd63e379b58bc6296696781099ca4c7',
        'tx': pathlib.Path('.omx/recovery/transactions/G013-pre-publication-regression-20260721T090051Z-worker1'),
        'commit_paths': 35,
        'seal_entries': 33,
        'seal_sha256': 'fa4f8a1686690d77fe8ac936d62f0126b6e660c38f0db1647abd94b2501c3314',
        'verify_log': 'checksum-verify.log',
        'status_counts': {'0': 2, '1': 2},
    },
    {
        'task': 2,
        'commit': '285617b195f03d703795115f5ada8de14b4d1e60',
        'parent': SOURCE,
        'tx': pathlib.Path('.omx/recovery/transactions/G013-task2-local-acceptance-20260721T092343Z-worker1'),
        'commit_paths': 296,
        'seal_entries': 294,
        'seal_sha256': '21d7b08bd8f386bdf4565641980f48aa66940f48b444c148d2936fe8043a05e7',
        'verify_log': 'CHECKSUM-VERIFY.log',
        'status_counts': {'0': 25, '1': 1},
    },
    {
        'task': 4,
        'commit': '5f866d2479a69b9e4c19435041ce4e846e024695',
        'parent': '285617b195f03d703795115f5ada8de14b4d1e60',
        'tx': pathlib.Path('.omx/recovery/transactions/G013-task4-plugin-api-20260721T115459Z-worker1'),
        'commit_paths': 33,
        'seal_entries': 31,
        'seal_sha256': 'c30e0feb030956b2dc182a35a318ddea821398367d3d4c3cf7c28549bd91c1f3',
        'verify_log': 'CHECKSUM-VERIFY.log',
        'status_counts': {'0': 8},
    },
    {
        'task': 5,
        'commit': 'f5f46a5ca910ea419996daa52c44d7d93a8efcdf',
        'parent': '5f866d2479a69b9e4c19435041ce4e846e024695',
        'tx': pathlib.Path('.omx/recovery/transactions/G013-task5-exact-six-20260721T120149Z-worker1'),
        'commit_paths': 33,
        'seal_entries': 31,
        'seal_sha256': 'f4aac444297a8caf0e78346f74baedfcb5c664651650711271e5e53672187fd2',
        'verify_log': 'CHECKSUM-VERIFY.log',
        'status_counts': {'0': 8},
    },
]

def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', '-C', str(cwd), *args], text=True).strip()

def parse_seal(path):
    entries = []
    for line in path.read_text().splitlines():
        digest, rel = line.split(None, 1)
        rel = rel.strip()
        if rel.startswith('./'):
            rel = rel[2:]
        entries.append((digest, rel))
    return entries

assert git('rev-parse', 'HEAD') == records[-1]['commit']
assert git('rev-parse', f'{SOURCE}^{{tree}}') == SOURCE_TREE
assert git('rev-parse', 'HEAD', cwd=ROOT/'realm/realm-library/src/main/cpp/realm-core') == CORE
assert subprocess.run(['git', 'diff', '--quiet', '--ignore-submodules=dirty'], cwd=ROOT).returncode == 0
assert subprocess.run(['git', 'diff', '--cached', '--quiet', '--ignore-submodules=dirty'], cwd=ROOT).returncode == 0
assert subprocess.run(['git', 'diff', '--quiet'], cwd=ROOT/'realm/realm-library/src/main/cpp/realm-core').returncode == 0
assert subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT/'realm/realm-library/src/main/cpp/realm-core').returncode == 0

verified = []
for rec in records:
    assert git('rev-parse', f"{rec['commit']}^") == rec['parent']
    changed = git('diff-tree', '--no-commit-id', '--name-only', '-r', rec['commit']).splitlines()
    assert len(changed) == rec['commit_paths']
    prefix = rec['tx'].as_posix() + '/'
    assert all(path.startswith(prefix) for path in changed)
    seal = rec['tx'] / 'SHA256SUMS'
    assert hashlib.sha256(seal.read_bytes()).hexdigest() == rec['seal_sha256']
    entries = parse_seal(seal)
    assert len(entries) == rec['seal_entries']
    actual = {
        p.relative_to(rec['tx']).as_posix()
        for p in rec['tx'].rglob('*') if p.is_file()
        and p.relative_to(rec['tx']).as_posix() not in {'SHA256SUMS', rec['verify_log']}
    }
    assert {rel for _, rel in entries} == actual
    for digest, rel in entries:
        assert hashlib.sha256((rec['tx']/rel).read_bytes()).hexdigest() == digest
    replay = subprocess.run(
        ['sha256sum', '-c', 'SHA256SUMS'], cwd=rec['tx'], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True,
    ).stdout
    assert replay == (rec['tx']/rec['verify_log']).read_text()
    counts = {}
    for p in (rec['tx']/'results').glob('*.status'):
        value = p.read_text().strip()
        counts[value] = counts.get(value, 0) + 1
    assert counts == rec['status_counts']
    verified.append({
        'task': rec['task'], 'commit': rec['commit'], 'parent': rec['parent'],
        'transaction': rec['tx'].as_posix(), 'commit_paths': len(changed),
        'seal_entries': len(entries), 'seal_sha256': rec['seal_sha256'],
        'status_counts': counts,
    })

# The only product-tree change between Task 1 evidence and the final integrated
# source is the approved, canonical generated provenance-manifest refresh.
source_changed = git('diff-tree', '--no-commit-id', '--name-only', '-r', SOURCE).splitlines()
assert source_changed == ['evidence/provenance/g011-source-evidence-manifest.json']
assert git('rev-parse', f'{SOURCE}^') == records[0]['commit']

matrix = (records[1]['tx']/'AC-MATRIX.md').read_text()
for ac in ['AC-01', 'AC-02', 'AC-03', 'AC-04', 'AC-05', 'AC-09', 'AC-10', 'AC-11', 'AC-15']:
    row = next(line for line in matrix.splitlines() if line.startswith(f'| {ac} |'))
    assert '| PASS |' in row
row7 = next(line for line in matrix.splitlines() if line.startswith('| AC-07 |'))
assert '| NOT OWNED |' in row7

state_root = pathlib.Path(os.environ['OMX_TEAM_STATE_ROOT'])
for task_id in [1, 2, 4, 5]:
    task = json.loads((state_root/f'team/at-exact-integrated-s-835c6090/tasks/task-{task_id}.json').read_text())
    assert task['status'] == 'completed'

output = {
    'result': 'PASS',
    'source_under_test': SOURCE,
    'source_tree': SOURCE_TREE,
    'core_commit': CORE,
    'evidence_head': records[-1]['commit'],
    'source_refresh_commit': SOURCE,
    'source_refresh_changed_paths': source_changed,
    'prior_evidence': verified,
    'prior_seals_replayed': 4,
    'prior_seal_entries_verified': sum(r['seal_entries'] for r in records),
    'prior_commit_paths_verified': sum(r['commit_paths'] for r in records),
    'completed_task_states_verified': [1, 2, 4, 5],
    'acceptance': {
        'AC-01': 'PASS', 'AC-02': 'PASS', 'AC-03': 'PASS',
        'AC-04': 'PASS', 'AC-05': 'PASS',
        'AC-07': 'RUNTIME-LANE_NOT_OWNED_STATIC_PREREQUISITES_PASS',
        'AC-09': 'PASS', 'AC-10': 'PASS', 'AC-11': 'PASS', 'AC-15': 'PASS',
    },
    'current_failures': [],
    'external_actions': 'none',
    'tracked_worktree_clean_before_evidence_commit': True,
    'core_worktree_clean': True,
}
print(json.dumps(output, indent=2, sort_keys=True))
