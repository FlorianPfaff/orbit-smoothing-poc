#!/usr/bin/env python3
"""Independent read-only audit of the dated preparation/recovery publication."""
import collections
import datetime
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path('/mnt/d/orbit-segmented-v4/publication-status-preparation-original150-02')
OUT = Path('/mnt/d/orbit-segmented-v4/control/status-publication02-independent-review01.json')
EXPECTED = '7954f136f7a32b76dca7c52c06e518a0789e4006c04a83f7cadbc14710825cd7'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check_record(record):
    path = Path(record['path'])
    assert path.is_file(), path
    assert digest(path) == record['sha256'], path
    if 'bytes' in record:
        assert path.stat().st_size == record['bytes'], path

def main():
    assert not OUT.exists(), OUT
    assert digest(ROOT / 'manifest.json') == EXPECTED
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    entries = manifest['entries']
    names = [e['relative'] for e in entries]
    assert len(names) == len(set(names))
    actual = set()
    for path in ROOT.rglob('*'):
        assert not path.is_symlink(), path
        if path.is_file():
            actual.add(path.relative_to(ROOT).as_posix())
    assert actual == set(names) | {'manifest.json'}
    for e in entries:
        rel = Path(e['relative'])
        assert not rel.is_absolute() and '..' not in rel.parts
        path = ROOT / rel
        assert path.stat().st_size == e['bytes'] and digest(path) == e['sha256'], rel
        text = path.read_text(encoding='utf-8')
        assert '\x00' not in text
        assert path.suffix in {'.json', '.html', '.log', '.stderr', '.txt', '.py'}
        assert not any(token in rel.name for token in ['.rows.', '.npz', '.npy', '.bin'])
    assert sum(e['bytes'] for e in entries) == manifest['bytes']
    status = json.loads((ROOT / 'status.json').read_text())
    for record in status['sources']:
        check_record(record)
    for record in status['remote_capture_records']:
        p = ROOT / 'remote' / record['relative']
        assert digest(p) == record['sha256'] and p.stat().st_size == record['bytes']
    check_record(manifest['source_helper'])
    check_record(manifest['previous_snapshot_manifest'])
    assert status['release_ready'] is False and manifest['release_ready'] is False
    assert status['v4_benchmark_executed_fits'] == 0 and status['v4_planned_fits'] == 68
    assert status['validation03_stages_passed'] == 14
    results = list((ROOT / 'original150-interruption/original150/checkpoints').glob('*/result.json'))
    results.append(ROOT / 'original150-append/result.json')
    assert len(results) == 7
    counts = collections.Counter(json.loads(p.read_text())['status'] for p in results)
    assert dict(counts) == {'failed': 2, 'timeout': 4, 'interrupted': 1}
    assert status['original150']['checkpoint_distribution'] == dict(counts)
    assert status['original150']['terminal_checkpoints'] == 7
    assert status['original150']['not_started'] == 143
    assert status['original150']['successful_fits'] == 0
    seventh = json.loads((ROOT / 'original150-append/result.json').read_text())
    assert seventh['covariance_valid'] is False and seventh['converged'] is False
    assert seventh['elapsed_seconds'] is None and seventh['final_objective'] is None
    audit = json.loads((ROOT / status['original150']['append_audit']).read_text())
    assert audit['passed'] is True
    assert [e['status'] for e in status['preparation_startup_attempts']] == ['failed', 'failed', 'passed']
    pipeline = json.loads((ROOT / status['preparation_first_run']['pipeline']).read_text())
    assert pipeline['status'] == 'failed_or_blocked'
    assert status['preparation_first_run']['completed_multiday_realizations'] == 0
    assert 'unrecorded cached input' in (ROOT / status['preparation_first_run']['traceback']).read_text()
    class Links(HTMLParser):
        def __init__(self):
            super().__init__(); self.links = []
        def handle_starttag(self, tag, attrs):
            if tag == 'a':
                self.links += [v for k, v in attrs if k == 'href']
    parser = Links(); parser.feed((ROOT / 'index.html').read_text())
    for link in parser.links:
        assert (ROOT / link).is_file(), link
    receipt = {
        'schema': 'orbit-poc-dated-status-publication-independent-review-v1',
        'reviewer': '/root', 'passed': True,
        'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'manifest': {'path': str(ROOT / 'manifest.json'), 'sha256': EXPECTED},
        'helper': {'path': __file__, 'sha256': digest(Path(__file__))},
        'text_members': len(actual), 'payload_bytes_excluding_manifest': manifest['bytes'],
        'source_records_rehashed': len(status['sources']),
        'remote_capture_members_verified': len(status['remote_capture_records']),
        'local_links_verified': len(parser.links), 'terminal_distribution': dict(counts),
        'v4_fits': 0, 'release_ready': False,
        'scope': 'Publication integrity and conservative interpretation of the dated snapshot. Earlier independent scientific audits remain separate. Subsequent launches are not represented as completed work in this snapshot.',
    }
    OUT.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'passed': True, 'receipt': str(OUT), 'sha256': digest(OUT)}))

if __name__ == '__main__':
    main()
