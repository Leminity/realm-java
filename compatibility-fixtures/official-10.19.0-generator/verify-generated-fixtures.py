#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit('usage: verify-generated-fixtures.py <fixture-dir> <expected-key-sha256>')
root = Path(sys.argv[1])
expected_key_hash = sys.argv[2]
manifest = json.loads((root / 'fixture-manifest.json').read_text())
assert manifest['realm_version'] == '10.19.0'
assert manifest['official_reader_semantic_validation'] is True
assert manifest['encryption_key_sha256'] == expected_key_hash
for label, name, field in (
    ('plain', 'official-10.19.0-plain.realm', 'plain_fixture_sha256'),
    ('encrypted', 'official-10.19.0-encrypted.realm', 'encrypted_fixture_sha256'),
):
    content = (root / name).read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    assert actual == manifest[field], f'{label} fixture SHA-256 mismatch: {actual} != {manifest[field]}'
print('PASS: official reader manifest, key fingerprint, and plain/encrypted fixture hashes verified')
