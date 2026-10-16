#!/usr/bin/env python3
"""Independent integrity and interpretation audit of the dated failure snapshot."""
from pathlib import Path
from html.parser import HTMLParser
from collections import Counter
import datetime, hashlib, json, xml.etree.ElementTree as ET

ROOT = Path('/mnt/d/orbit-segmented-v4/publication-status-preparation-original150-03')
OUT = Path('/mnt/d/orbit-segmented-v4/control/status-publication03-independent-review01.json')
EXPECTED = '85a26ca21a051e26a2a4bbeb96fe182aaa9047e425a391390c0d9a16085abf31'

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())
def verify(record, path=None):
    p = Path(path or record['path'])
    assert p.is_file() and not p.is_symlink() and sha(p) == record['sha256'], p
    if 'bytes' in record: assert p.stat().st_size == record['bytes'], p

def main():
    assert not OUT.exists()
    assert sha(ROOT/'manifest.json') == EXPECTED
    manifest, status = read(ROOT/'manifest.json'), read(ROOT/'status.json')
    entries = manifest['entries']
    names = [e['relative'] for e in entries]
    assert len(names) == len(set(names)) == manifest['files'] == 64
    actual = set()
    for path in ROOT.rglob('*'):
        assert not path.is_symlink(), path
        if path.is_file(): actual.add(path.relative_to(ROOT).as_posix())
    assert actual == set(names) | {'manifest.json'}
    for e in entries:
        rel = Path(e['relative']); assert not rel.is_absolute() and '..' not in rel.parts
        verify(e, ROOT/rel)
        assert (ROOT/rel).suffix in {'.json','.html','.log','.txt','.py','.xml'}
        assert '\x00' not in (ROOT/rel).read_text()
    assert sum(e['bytes'] for e in entries) == manifest['bytes']
    verify(manifest['source_helper']); verify(manifest['previous_snapshot_manifest'])
    local_count = remote_count = 0
    for e in status['sources']:
        verify(e['source'], ROOT/e['relative'])
        if Path(e['source']['path']).is_file():
            verify(e['source']); local_count += 1
        else:
            assert e['source']['path'].startswith('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/')
            remote_count += 1
    assert status['release_ready'] is False and manifest['release_ready'] is False
    v4 = status['v4']; assert v4['planned_fits'] == 68
    assert v4['terminal_fits'] == v4['started_fits'] == 0
    assert v4['correction_demonstrated'] is False and v4['final_manifest_exists'] is False
    failure = read(ROOT/v4['independent_audit']); assert failure['passed'] is True
    closure = read(ROOT/'preparation05/48h-initialization.json')
    assert closure['status'] == 'failed' and closure['converged'] is False
    assert closure['maximum_iterations'] == 10 and len(closure['iterations']) == 10
    assert closure['position_tolerance_m'] == v4['position_tolerance_m'] == 2e-6
    assert closure['velocity_tolerance_m_s'] == v4['velocity_tolerance_m_s'] == 3e-9
    assert all(not x['closed'] for x in closure['iterations'])
    last = closure['iterations'][-1]
    assert last['maximum_position_change_m'] == v4['last_position_change_m']
    assert last['maximum_velocity_change_m_s'] == v4['last_velocity_change_m_s']
    assert len(closure['executions']) == 11 and all(e['returncode'] == 0 for e in closure['executions'])
    configs = sorted((ROOT/'preparation05/configurations').glob('*.xml'))
    assert len(configs) == 11
    for p in configs:
        nodes = ET.parse(p).findall('.//PreprocessingVariationalEquation')
        assert len(nodes) == 1 and nodes[0].find('orbitPocDerivativeProfile') is None
    results = sorted((ROOT/'original150').glob('*/result.json'))
    assert len(results) == 8
    counts = Counter(read(p)['status'] for p in results)
    assert dict(counts) == {'failed':3,'timeout':4,'interrupted':1}
    original = status['original150']
    assert original['terminal_attempts'] == 8 and original['planned_attempts'] == 150
    assert original['terminal_distribution'] == dict(counts) and original['successful_fits'] == 0
    assert original['corrected_executable_substituted'] is False
    audit = read(ROOT/original['independent_audit']); assert audit['passed'] is True
    assert original['ninth']['observed_at'] == audit['observed_at']
    for e in audit['terminal_prefix']:
        for key in ('result','index'):
            verify(e[key], ROOT/'original150'/e['attempt_id']/Path(e[key]['path']).name)
    eighth = read(ROOT/'original150'/original['eighth']['attempt_id']/'result.json')
    assert eighth['status'] == 'failed' and eighth['converged'] is False and eighth['covariance_valid'] is False
    assert '429' in (ROOT/'original150/estimate.log').read_text()
    class Links(HTMLParser):
        def __init__(self): super().__init__(); self.links=[]
        def handle_starttag(self, tag, attrs):
            if tag == 'a': self.links.extend(v for k,v in attrs if k == 'href')
    parser=Links(); parser.feed((ROOT/'index.html').read_text()); local_links=0
    for link in parser.links:
        if link.startswith('https://'):
            assert link.startswith('https://github.com/FlorianPfaff/orbit-smoothing-poc/releases/tag/')
        elif link.startswith('../status-preparation-original150-02/'):
            assert (ROOT.parent/'publication-status-preparation-original150-02'/link.split('/',2)[2]).is_file()
            local_links += 1
        else:
            assert (ROOT/link).is_file(), link
            local_links += 1
    receipt={'schema':'orbit-poc-dated-status-publication-independent-review-v1','passed':True,
        'reviewer':'/root','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'manifest':{'path':str(ROOT/'manifest.json'),'sha256':EXPECTED},
        'helper':{'path':__file__,'sha256':sha(__file__)},'text_members':len(actual),
        'local_source_records_rehashed':local_count,'remote_copies_verified_against_sealed_capture_pins':remote_count,
        'remote_scope':'Actual remote trajectory recomputation/ownership verified by the separately retained independent failure audit; this audit checks publication copies.',
        'local_links_verified':local_links,'terminal_distribution':dict(counts),'v4_fits':0,'release_ready':False,
        'scope':'Dated failure evidence before the separate successful profile diagnostic; no current completion or release claim.'}
    OUT.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'passed':True,'receipt':str(OUT),'sha256':sha(OUT)}))

if __name__=='__main__': main()
