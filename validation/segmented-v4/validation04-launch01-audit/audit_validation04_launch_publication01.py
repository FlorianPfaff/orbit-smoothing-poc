#!/usr/bin/env python3
"""Independent integrity/scope audit of a dated validation-launch publication."""
from pathlib import Path
from html.parser import HTMLParser
import datetime
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT = Path('/mnt/d/orbit-segmented-v4/publication-validation04-launch-01')
CONTROL = ROOT.parent / 'control'
OUT = CONTROL / 'validation04-launch-publication-root-review01.json'
EXPECTED = 'f412e95c94ccf9968c6c62167e1918abcd4a9b290da5dbf225f6eb2e18cec324'

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def read(p):
    return json.loads(Path(p).read_text())

def verify(pin, p=None):
    p = Path(p or pin['path'])
    assert p.is_file() and not p.is_symlink() and sha(p) == pin['sha256'], p
    if 'bytes' in pin:
        assert p.stat().st_size == pin['bytes'], p

def main():
    assert not OUT.exists()
    assert sha(ROOT / 'manifest.json') == EXPECTED
    manifest = read(ROOT / 'manifest.json')
    entries = manifest['entries']
    names = [e['relative'] for e in entries]
    assert len(names) == len(set(names)) == manifest['files'] == 89
    actual = set()
    for path in ROOT.rglob('*'):
        assert not path.is_symlink(), path
        if path.is_file():
            actual.add(path.relative_to(ROOT).as_posix())
    assert actual == set(names) | {'manifest.json'}
    for entry in entries:
        rel = Path(entry['relative'])
        assert not rel.is_absolute() and '..' not in rel.parts
        path = ROOT / rel
        verify(entry, path)
        assert path.suffix in {'.json', '.py', '.xml', '.log', '.txt', '.html', '.patch'}
        assert '\x00' not in path.read_text()
    assert sum(e['bytes'] for e in entries) == manifest['bytes']
    verify(manifest['source_helper'])
    verify(manifest['staging_helper'])
    assert manifest['release_ready'] is False and manifest['full_suite_passed'] is False
    status = read(ROOT / 'status.json')
    audit = read(ROOT / status['launch']['independent_audit'])
    assert audit['passed'] is True
    assert sha(ROOT / status['launch']['independent_audit']) == '6a6a3a4a1e61f9fc3d0c8c8d6274b9a14cb9825edecf6034d32765442603666d'
    assert status['observed_at'] == audit['reviewed_utc']
    assert status['complete_validation_claimed'] is False and status['release_ready'] is False
    assert status['benchmark_fits_started'] == status['benchmark_fits_completed'] == 0
    assert len(status['planned_stage_names']) == len(set(status['planned_stage_names'])) == 14
    assert status['planned_stage_names'] == [x['name'] for x in audit['stages']]
    verify(audit['launch'], ROOT / status['launch']['receipt'])
    verify(audit['plan'], ROOT / 'controls/launch-plan.json')
    assert status['launch']['pid'] == audit['owned_driver']['pid'] == 2374220
    assert status['launch']['start_ticks'] == audit['owned_driver']['start_ticks'] == 111009241
    assert all(audit['checks'].values())
    counts = {}
    gates = status['independently_checked_completed_gates']
    assert gates == audit['completed_test_gates']
    assert [g['name'] for g in gates] == ['native-tests', 'correction-tests']
    for gate in gates:
        folder = ROOT / 'gates' / gate['name']
        verify(gate['execution'], folder / 'execution.json')
        verify(gate['junit'], folder / 'tests.xml')
        cases = ET.parse(folder / 'tests.xml').findall('.//testcase')
        assert len(cases) == gate['counts']['tests'] == {'native-tests': 106, 'correction-tests': 51}[gate['name']]
        assert len({(c.get('classname'), c.get('name')) for c in cases}) == len(cases)
        assert not any(c.find(tag) is not None for c in cases for tag in ('failure', 'error', 'skipped'))
        assert gate['counts'] == dict(tests=len(cases), failures=0, errors=0, skipped=0)
        counts[gate['name']] = len(cases)
    source = status['source_change']
    assert source['source_sha256'] == '1fe0f24166a7983a7c10eaf1712e4b5545f02c61bd38406fa9d07e70cd7d6a4e'
    assert source['comparison_source_sha256'] == '68e17e5b5ebe6fe22a47b9c6213c89397cfb80e25cc5e033da2621fc0aa44474'
    assert source['native_build_inputs_unchanged'] == 70
    assert len(set(source['distinct_original_native_binaries'].values())) == 2
    assert len(source['changed_paths']) == 3
    assert sha(ROOT / source['source_scope_clarification']) == 'de23dcd339b399ced680f9dc2db118c60aaf8d433766b7b1a99931117100ef96'
    assert status['focused_source_tests']['passed'] == 31 and status['focused_source_tests']['deselected_native_parametrizations'] == 2
    startup = status['startup']
    assert startup['numerical_gates_executed_by_startup'] is False
    assert startup['structural_collection'] == 303 and startup['native_tangent_collection'] == 3
    assert sha(ROOT / startup['audit']) == 'c275645b44f87e3bb15bbe86d35b7f56c334431a5dc3f10694baf57fa63f55ad'
    assert read(ROOT / startup['audit'])['passed'] is True

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []
        def handle_starttag(self, tag, attrs):
            if tag == 'a':
                self.links.extend(v for k, v in attrs if k == 'href')
    parser = Links()
    parser.feed((ROOT / 'index.html').read_text())
    for link in parser.links:
        if link.startswith('../'):
            first, rest = link[3:].split('/', 1)
            allowed = {'status-preparation-original150-03': 'publication-status-preparation-original150-03',
                       'nominal-profile-diagnostic01': 'publication-nominal-profile-diagnostic01'}
            assert first in allowed and '..' not in Path(rest).parts
            assert (ROOT.parent / allowed[first] / rest).is_file()
        else:
            assert not Path(link).is_absolute() and '..' not in Path(link).parts and (ROOT / link).is_file()
    receipt = {
        'schema': 'orbit-poc-dated-launch-publication-root-review-v1', 'passed': True,
        'reviewer': '/root', 'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'manifest': {'path': str(ROOT / 'manifest.json'), 'sha256': EXPECTED},
        'helper': {'path': __file__, 'sha256': sha(__file__)},
        'text_members': len(actual), 'verified_links': len(parser.links), 'checked_test_counts': counts,
        'full_suite_passed_claimed': False, 'benchmark_fits': 0, 'release_ready': False,
        'scope': 'Checks compact publication membership, hashes, interpretation, raw JUnit counts and links. Current remote ownership and source/runtime checks are established by the included separately authored independent audits; this review does not rerun native work or claim later progress.'
    }
    with OUT.open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'passed': True, 'receipt': str(OUT), 'sha256': sha(OUT)}))

if __name__ == '__main__':
    main()
