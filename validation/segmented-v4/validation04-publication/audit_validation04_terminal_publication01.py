"""Independently verify publication bytes and the scope of the audited results."""
from pathlib import Path
from html.parser import HTMLParser
import datetime, gzip, hashlib, json

BASE = Path('/mnt/d/orbit-segmented-v4')
EXPECTED = {
    'publication-validation04-terminal-full-01': '250cc2f17b6d140e59e569df9aed2e6cbd67c51409c69a7ab1bc89240c2a7094',
    'publication-validation04-terminal-git-01': '48cc9c4615c69c1d1d1141f2754dd95861981d156f93b773623ae635eaae2710',
    'publication-validation04-terminal-provenance-01': 'ea56c991f03006c3cf96ae4f5983820d981f7b92df892474620790d2bdad969f',
}

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())
def verify(pin, path=None):
    path = Path(path or pin['path'])
    assert path.is_file() and not path.is_symlink(), path
    assert sha(path) == pin['sha256'] and path.stat().st_size == pin['bytes'], path

def main():
    output = BASE/'control/validation04-terminal-publication-root-review01.json'
    assert not output.exists()
    manifests = {}
    for folder, digest in EXPECTED.items():
        root = BASE/folder
        assert sha(root/'manifest.json') == digest
        manifest = read(root/'manifest.json'); manifests[folder] = manifest
        names = [r['path'] for r in manifest['files']]
        assert len(names) == len(set(names))
        actual = set()
        for path in root.rglob('*'):
            assert not path.is_symlink(), path
            if path.is_file(): actual.add(path.relative_to(root).as_posix())
        assert actual == set(names) | {'manifest.json'}
        for item in manifest['files']:
            rel = Path(item['path'])
            assert not rel.is_absolute() and '..' not in rel.parts
            verify(item, root/rel)
            if 'original' in item: verify(item['original'])
        assert sum(r['bytes'] for r in manifest['files']) == manifest['bytes']
        verify(manifest['helper'])
        assert manifest['release_ready'] is False and manifest['benchmark_attempts_executed'] == 0

    full = BASE/'publication-validation04-terminal-full-01'
    git = BASE/'publication-validation04-terminal-git-01'
    fm, gm = (manifests[p.name] for p in (full, git))
    assert len(fm['files']) == 2698 and len(gm['files']) == 2671
    assert sha(git/'external-full-publication-manifest.json') == EXPECTED[full.name]
    omitted = gm['external_not_distributed']
    assert len(omitted) == 30
    for row in omitted:
        assert not (git/row['path']).exists()
        verify(row, full/row['path']); verify(row['external_artifact'])
    assert not list(git.rglob('*.npz')) and not list(git.rglob('*.npy'))
    full_index = {r['path']: r for r in fm['files']}
    special = {'index.html', 'external-evidence.json', 'external-full-publication-manifest.json', 'presentation-original-index.html'}
    for row in gm['files']:
        if row['path'] not in special: assert row == full_index[row['path']], row['path']
    assert sha(git/'presentation-original-index.html') == sha(full/'index.html')
    assert sha(git/'independent-audit.json') == '06fd170a383214cdade87bddcb925d465184825a47281093f4aaad2043e863d0'
    audit = read(git/'independent-audit.json')
    assert audit['consistency_passed'] and audit['cleanup_verified']
    assert audit['scientific_status'] == 'passed_scoped_checks'
    assert audit['release_ready'] is False and audit['fit_covariance_authorized'] is False
    assert len(audit['stages']) == 14 and all(s['status']=='passed' and s['independently_consistent'] for s in audit['stages'])
    stages = {s['name']: s for s in audit['stages']}
    for name, count in [('native-tests',106),('correction-tests',51),('segmented-native-tangent',3),('segmented-structural',303)]:
        metrics = stages[name]['measurements']
        assert metrics['passed'] == count and metrics['failures'] == metrics['errors'] == metrics['skipped'] == 0
    assert stages['objective-log_drag_ou']['measurements']['accepted_consecutive_scales'] == [0.125,0.0625]
    for name in ('objective-log_drag_ou','objective-pulses'):
        assert stages[name]['measurements']['floor_limited_profiles'] == 0
    summary = read(git/'summary.json')
    assert summary['scientific_status']=='passed_scoped_checks' and summary['pipeline_status']=='passed'
    assert summary['expected_attempts']==68 and summary['benchmark_attempts_executed']==0
    assert summary['execution_complete'] is False and summary['release_ready'] is False and summary['fit_covariance_authorized'] is False
    assert len(summary['attempts'])==68 and len({a['attempt_id'] for a in summary['attempts']})==68
    assert summary['identity']==audit['identity']

    class Links(HTMLParser):
        def __init__(self): super().__init__(); self.links=[]
        def handle_starttag(self,tag,attrs):
            if tag=='a': self.links.extend(v for k,v in attrs if k=='href')
    links=Links(); links.feed((git/'index.html').read_text())
    for link in links.links:
        path=link.split('#',1)[0]
        if not path: continue
        assert not path.startswith(('https:', 'http:', '/')) and '..' not in Path(path).parts, link
        assert (git/path).is_file(), link
    receipt={
        'schema':'orbit-poc-validation-terminal-publication-root-review-v1', 'passed':True,
        'reviewer':'/root', 'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'manifests':{name:{'path':str(BASE/name/'manifest.json'),'sha256':digest} for name,digest in EXPECTED.items()},
        'helper':{'path':__file__,'sha256':sha(__file__)},
        'full_members':2699,'git_members':2672,'provenance_members':42,'external_numerical_members':30,
        'local_html_links_verified':len(links.links),'passed_validation_stages':14,'benchmark_attempts':0,'release_ready':False,
        'scope':'Publication integrity and interpretation. Native scientific recomputation and owned cleanup are established by the separately authored preserved independent terminal audit; no fit/release/covariance approval.'}
    with output.open('x') as stream: json.dump(receipt,stream,indent=2);stream.write('\n')
    print(json.dumps({'passed':True,'receipt':str(output),'sha256':sha(output)}))

if __name__=='__main__': main()
