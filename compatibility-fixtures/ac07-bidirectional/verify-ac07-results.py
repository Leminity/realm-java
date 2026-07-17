#!/usr/bin/env python3
"""Host-side guard for AC-07 result exports; it never writes fixture input files."""
import hashlib
import json
from pathlib import Path
import sys

if len(sys.argv) != 4:
    raise SystemExit('usage: verify-ac07-results.py <official-fixture-dir> <fork-export-dir> <fork-report.json>')

original, exported, report_path = map(Path, sys.argv[1:])
manifest = json.loads((original / 'fixture-manifest.json').read_text())
report = json.loads(report_path.read_text())
for label, filename, manifest_field in (
    ('plain', 'official-10.19.0-plain.realm', 'plain_fixture_sha256'),
    ('encrypted', 'official-10.19.0-encrypted.realm', 'encrypted_fixture_sha256'),
):
    original_hash = hashlib.sha256((original / filename).read_bytes()).hexdigest()
    assert original_hash == manifest[manifest_field], f'{label} immutable input hash differs from manifest'
    assert report[label]['source_sha256'] == original_hash, f'{label} fork report did not preserve source hash'
    assert report[label]['migration_callbacks'] == 0, f'{label} unexpectedly invoked migration'
    modified_hash = hashlib.sha256((exported / filename).read_bytes()).hexdigest()
    assert modified_hash == report[label]['working_sha256'], f'{label} exported working copy hash differs from fork report'
    assert modified_hash != original_hash, f'{label} CRUD working copy did not differ from immutable original'
assert report['encrypted']['wrong_key_rejected'] is True, 'wrong encrypted key was accepted'
print('PASS: AC-07 immutable inputs, zero migrations, fork working copies, and wrong-key rejection verified')
