#!/usr/bin/env python3
import collections
import hashlib
import json
import pathlib
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = pathlib.Path.cwd()
T2 = ROOT / '.omx/recovery/transactions/G013-task2-local-acceptance-20260721T092343Z-worker1'
G008 = T2 / 'artifacts/g008'
STAGING = G008 / 'staging'
GROUP = 'io.github.leminity.realm'
VERSION = '10.19.0-agp9.1'
ARTIFACTS = [
    'realm-gradle-plugin',
    'realm-transformer',
    'realm-annotations',
    'realm-annotations-processor',
    'realm-android-library',
    'realm-android-kotlin-extensions',
]
COORDS = [f'{GROUP}:{artifact}:{VERSION}' for artifact in ARTIFACTS]
EXPECTED_KEYS = {
    'artifacts', 'coordinates', 'dynamic_plugin_injection', 'files',
    'format', 'group', 'normalized_pom_dependencies', 'version',
}
OMITTED_PATH = (
    f'io/github/leminity/realm/realm-android-library/{VERSION}/'
    f'realm-android-library-{VERSION}.aar'
)
OMITTED_SHA = 'af0c1fb414dac2fec16cadcf5fbf7cc1cbea209a4c07d7ea2c7675d5043fba4d'
BUNDLE_SHA = '1fc4bcfddb24a214ed89f646007bbe14cb466924bfb948c65a64309253678cf0'

manifest = json.loads((G008 / 'publication-manifest.json').read_text())
assert set(manifest) == EXPECTED_KEYS
assert manifest['group'] == GROUP
assert manifest['version'] == VERSION
assert manifest['coordinates'] == COORDS
assert set(manifest['artifacts']) == set(ARTIFACTS)
assert set(manifest['normalized_pom_dependencies']) == set(ARTIFACTS)
assert manifest['dynamic_plugin_injection'] == [
    {'artifactId': 'realm-annotations', 'kind': 'annotation-api'},
    {'artifactId': 'realm-annotations-processor', 'kind': 'annotation-processor'},
    {'artifactId': 'realm-android-library', 'kind': 'base-library'},
    {'artifactId': 'realm-android-kotlin-extensions', 'kind': 'kotlin-extension'},
]

entries = manifest['files']
assert len(entries) == 144
by_path = {entry['path']: entry for entry in entries}
assert len(by_path) == 144
all_names = []
for artifact in ARTIFACTS:
    names = manifest['artifacts'][artifact]
    assert len(names) == 24
    expected_dir = f"io/github/leminity/realm/{artifact}/{VERSION}"
    artifact_paths = {p for p in by_path if p.startswith(expected_dir + '/')}
    assert artifact_paths == {f'{expected_dir}/{name}' for name in names}
    all_names.extend(names)
assert len(all_names) == len(set(all_names)) == 144

suffix_counts = {
    'asc': sum(name.endswith('.asc') for name in all_names),
    'md5': sum(name.endswith('.md5') for name in all_names),
    'sha1': sum(name.endswith('.sha1') for name in all_names),
    'sha256': sum(name.endswith('.sha256') for name in all_names),
    'sha512': sum(name.endswith('.sha512') for name in all_names),
    'sources': sum(name.endswith('-sources.jar') for name in all_names),
    'javadoc': sum(name.endswith('-javadoc.jar') for name in all_names),
    'pom': sum(name.endswith('.pom') for name in all_names),
}
assert suffix_counts == {
    'asc': 24, 'md5': 24, 'sha1': 24, 'sha256': 24, 'sha512': 24,
    'sources': 6, 'javadoc': 6, 'pom': 6,
}
primary_names = [
    name for name in all_names
    if not name.endswith(('.asc', '.md5', '.sha1', '.sha256', '.sha512', '.pom', '-sources.jar', '-javadoc.jar'))
]
assert len(primary_names) == 6

missing = []
retained_verified = 0
for rel, entry in by_path.items():
    path = STAGING / rel
    if not path.is_file():
        missing.append(rel)
        continue
    payload = path.read_bytes()
    assert len(payload) == entry['size']
    assert hashlib.sha256(payload).hexdigest() == entry['sha256']
    retained_verified += 1
assert retained_verified == 143
assert missing == [OMITTED_PATH]
assert by_path[OMITTED_PATH]['sha256'] == OMITTED_SHA

algorithms = {
    '.md5': hashlib.md5,
    '.sha1': hashlib.sha1,
    '.sha256': hashlib.sha256,
    '.sha512': hashlib.sha512,
}
checksum_payloads_verified = 0
omitted_checksum_sidecars = 0
for rel in sorted(by_path):
    suffix = next((s for s in algorithms if rel.endswith(s)), None)
    if suffix is None:
        continue
    sidecar = STAGING / rel
    payload = STAGING / rel[:-len(suffix)]
    assert sidecar.is_file()
    recorded = sidecar.read_text().strip().split()[0]
    if payload.is_file():
        assert recorded == algorithms[suffix](payload.read_bytes()).hexdigest()
        checksum_payloads_verified += 1
    else:
        assert rel[:-len(suffix)] == OMITTED_PATH
        omitted_checksum_sidecars += 1
        if suffix == '.sha256':
            assert recorded == OMITTED_SHA
assert checksum_payloads_verified == 92
assert omitted_checksum_sidecars == 4

signature_files = sorted(STAGING.rglob('*.asc'))
assert len(signature_files) == 24
for path in signature_files:
    text = path.read_text()
    assert text.startswith('-----BEGIN PGP SIGNATURE-----\n')
    assert text.rstrip().endswith('-----END PGP SIGNATURE-----')
with tempfile.TemporaryDirectory(prefix='task5-gpg-') as home:
    for path in signature_files:
        proc = subprocess.run(
            ['gpg', '--batch', '--no-options', '--homedir', home, '--list-packets', str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        assert proc.returncode == 0

inventory_lines = (G008 / 'staging-captured-logical-inventory.sha256').read_text().splitlines()
assert len(inventory_lines) == 144
inventory = {}
for line in inventory_lines:
    digest, rel = line.split('  ./', 1)
    inventory[rel] = digest
assert inventory == {rel: entry['sha256'] for rel, entry in by_path.items()}

listing = (G008 / 'bundle-captured-listing.txt').read_text()
assert 'number of entries: 144' in listing
for rel in by_path:
    assert listing.count(' ' + rel + '\n') == 1
bundle_sha_line = (G008 / 'bundle-captured.sha256').read_text().strip()
assert bundle_sha_line.split()[0] == BUNDLE_SHA
omitted_text = (G008 / 'OMITTED-PAYLOADS.txt').read_text()
assert OMITTED_SHA in omitted_text and OMITTED_PATH in omitted_text
assert BUNDLE_SHA in omitted_text and 'maven-central-bundle.zip' in omitted_text

ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
def one(root, query):
    node = root.find(query, ns)
    assert node is not None and node.text
    return node.text.strip()
def normalized_dependencies(root):
    result = []
    for dep in root.findall('./m:dependencies/m:dependency', ns):
        exclusions = []
        for exclusion in dep.findall('./m:exclusions/m:exclusion', ns):
            exclusions.append([
                one(exclusion, './m:groupId'), one(exclusion, './m:artifactId')
            ])
        result.append({
            'artifactId': one(dep, './m:artifactId'),
            'exclusions': exclusions,
            'groupId': one(dep, './m:groupId'),
            'scope': (dep.find('./m:scope', ns).text.strip() if dep.find('./m:scope', ns) is not None and dep.find('./m:scope', ns).text else 'compile'),
            'version': one(dep, './m:version'),
        })
    return result

def canonical_rows(rows):
    return sorted(json.dumps(row, sort_keys=True) for row in rows)

poms_verified = 0
for artifact in ARTIFACTS:
    rel = f'io/github/leminity/realm/{artifact}/{VERSION}/{artifact}-{VERSION}.pom'
    root = ET.parse(STAGING / rel).getroot()
    assert one(root, './m:groupId') == GROUP
    assert one(root, './m:artifactId') == artifact
    assert one(root, './m:version') == VERSION
    assert one(root, './m:url') == 'https://github.com/Leminity/realm-java'
    assert one(root, './m:licenses/m:license/m:name') == 'The Apache Software License, Version 2.0'
    assert one(root, './m:licenses/m:license/m:url') == 'https://www.apache.org/licenses/LICENSE-2.0.txt'
    assert one(root, './m:scm/m:connection') == 'scm:git:https://github.com/Leminity/realm-java.git'
    assert one(root, './m:scm/m:url') == 'https://github.com/Leminity/realm-java'
    assert one(root, './m:developers/m:developer/m:id') == 'leminity'
    assert one(root, './m:developers/m:developer/m:name') == 'Leminity'
    actual_deps = normalized_dependencies(root)
    expected_deps = manifest['normalized_pom_dependencies'][artifact]
    assert canonical_rows(actual_deps) == canonical_rows(expected_deps)
    for dep in actual_deps:
        assert dep['groupId'] != 'io.realm'
        if dep['groupId'] == GROUP:
            assert dep['version'] == VERSION
    poms_verified += 1
assert poms_verified == 6

license_report = json.loads((T2 / 'artifacts/g010/license-report.json').read_text())
assert license_report['version'] == VERSION
assert set(license_report['artifacts']) == set(ARTIFACTS)
for artifact in ARTIFACTS:
    prefix = f'io/github/leminity/realm/{artifact}/{VERSION}/{artifact}-{VERSION}'
    candidates = manifest['artifacts'][artifact]
    primary = next(name for name in candidates if name in primary_names)
    expected = {
        'primary': by_path[f'io/github/leminity/realm/{artifact}/{VERSION}/{primary}']['sha256'],
        'sources': by_path[prefix + '-sources.jar']['sha256'],
        'javadoc': by_path[prefix + '-javadoc.jar']['sha256'],
        'pom_sha256': by_path[prefix + '.pom']['sha256'],
    }
    actual = license_report['artifacts'][artifact]
    assert actual['primary']['sha256'] == expected['primary']
    assert actual['sources']['sha256'] == expected['sources']
    assert actual['javadoc']['sha256'] == expected['javadoc']
    assert actual['pom_sha256'] == expected['pom_sha256']
assert license_report['artifacts']['realm-android-library']['primary']['sha256'] == OMITTED_SHA

scope_report = json.loads((T2 / 'artifacts/g010/scope-report.json').read_text())
assert scope_report['status'] == 'PASS'
assert scope_report['failures'] == []
assert scope_report['forbidden_runtime_hits'] == []
assert scope_report['forbidden_supported_graph_hits'] == []

result = dict(line.split('=', 1) for line in (T2 / 'artifacts/consumer/result.txt').read_text().splitlines() if line)
routing = dict(line.split('=', 1) for line in (T2 / 'artifacts/consumer/routing-proof.txt').read_text().splitlines() if line)
assert result == {'gradle_exit': '0'}
assert routing['mode'] == 'local'
assert routing['fork_group'] == GROUP
assert routing['exclusive_dependency_resolution'] == 'PASS'
assert routing['exclusive_plugin_resolution'] == 'PASS'
assert routing['maven_local'] == 'absent'
assert routing['jitpack'] == 'absent'
assert routing['gradle_user_home_initial_entries'] == '0'
dependency_report = (T2 / 'artifacts/consumer/dependency-report.txt').read_text()
assert 'G011 exact-six consumer: PASS' in dependency_report
assert 'BUILD SUCCESSFUL' in dependency_report

for status in [
    'results/g008-signed-bundle.status', 'results/g010-license.status',
    'results/g010-scope.status', 'results/g011-consume-six.status',
]:
    assert (T2 / status).read_text().strip() == '0'

output = {
    'result': 'PASS',
    'source_under_test': '188f0832252172a5ca93204292a65a0f8fe4f4f3',
    'task2_evidence_commit': '285617b195f03d703795115f5ada8de14b4d1e60',
    'group': GROUP,
    'version': VERSION,
    'coordinates': COORDS,
    'coordinate_count': 6,
    'manifest_schema_keys': sorted(EXPECTED_KEYS),
    'manifest_files': 144,
    'artifact_file_counts': {artifact: 24 for artifact in ARTIFACTS},
    'suffix_counts': suffix_counts,
    'primary_artifacts': 6,
    'retained_files_hash_verified': retained_verified,
    'omitted_payload_count': len(missing),
    'omitted_payload': {'path': OMITTED_PATH, 'sha256': OMITTED_SHA},
    'checksum_payloads_verified': checksum_payloads_verified,
    'omitted_payload_checksum_sidecars_authenticated': omitted_checksum_sidecars,
    'signature_packets_parsed': len(signature_files),
    'poms_metadata_and_dependencies_verified': poms_verified,
    'license_cross_bindings_verified': len(ARTIFACTS),
    'logical_inventory_entries_verified': len(inventory),
    'bundle_listing_entries_verified': len(by_path),
    'bundle_sha256': BUNDLE_SHA,
    'consumer': {
        'gradle_exit': 0,
        'mode': routing['mode'],
        'fork_group': routing['fork_group'],
        'exclusive_dependency_resolution': routing['exclusive_dependency_resolution'],
        'exclusive_plugin_resolution': routing['exclusive_plugin_resolution'],
        'maven_local': routing['maven_local'],
        'jitpack': routing['jitpack'],
    },
    'external_actions': 'none',
}
print(json.dumps(output, indent=2, sort_keys=True))
