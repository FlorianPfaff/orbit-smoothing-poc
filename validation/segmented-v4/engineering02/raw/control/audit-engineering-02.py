"""Independently preserve a terminal engineering02 run without promoting failures."""
from pathlib import Path
import hashlib
import json
import tarfile
import xml.etree.ElementTree as ET

R = Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/engineering-02')
EXPECTED_PLAN = '8e862523c7514e354d12067fae7fe9512b237a02bedda44642335babcca2c590'
EXPECTED_SOURCE = 'd1b33f7851b3ed59f372a7912e24d78aff8b85bf71f20c867f84a8127ef4d417'
COUNTS = {'native-tests':106, 'correction-tests':51, 'segmented-qr-tests':47, 'segmented-tangent-tests':3}
NAMES = ['namespace-smoke','clone','checkout','build','build-segmented-qr',*COUNTS,
         'native-linearization-pulses','native-linearization-log_drag_ou']

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''): h.update(block)
    return h.hexdigest()

def main():
    j = json.loads((R/'run/pipeline.json').read_text())
    p = json.loads((R/'control/plan.json').read_text())
    f = json.loads((R/'control/source-freeze.json').read_text())
    assert j['status'] in ('completed','failed') and j['final_cleanup']['verified'] and j['release_ready'] is False
    assert j['source'] == f['source'] and j['plan']['sha256'] == sha(R/'control/plan.json') == EXPECTED_PLAN
    for key in ('execution','runner','driver','source_freeze','previous_source_freeze'):
        assert sha(p[key]['path']) == p[key]['sha256']
    source = {str(x.relative_to(R/'source')):sha(x) for x in sorted((R/'source').rglob('*')) if x.is_file()}
    assert source == f['source']['files'] and len(source) == 372
    assert hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest() == f['source']['sha256'] == EXPECTED_SOURCE
    names = [s['name'] for s in j['steps']]
    assert len(names) == len(set(names)) and names == NAMES[:len(names)]
    steps = {s['name']:s for s in j['steps']}
    outcomes = {}
    for name in NAMES:
        s = steps.get(name)
        if s is None:
            outcomes[name] = {'status':'not_run'}
            continue
        assert s['status'] in ('completed','failed') and s.get('cleanup',{}).get('verified') is True
        outcomes[name] = {k:s.get(k) for k in ('status','returncode','elapsed_seconds','error','validation_error')}
        if name in COUNTS:
            path = R/'run'/f'{name}.xml'
            if path.exists():
                cases = list(ET.parse(path).getroot().iter('testcase'))
                counts = {'tests':len(cases),**{k:sum(c.find(k) is not None for c in cases) for k in ('failure','error','skipped')}}
                outcomes[name]['junit'] = counts
                if s['status'] == 'completed':
                    assert s['returncode'] == 0 and len(cases) == COUNTS[name] and not any(counts[k] for k in ('failure','error','skipped'))
            else:
                assert s['status'] == 'failed'
        if name.startswith('native-linearization-'):
            path = R/'run'/name/'validation.json'
            if path.exists():
                result = json.loads(path.read_text())
                outcomes[name]['validation_passed'] = result['passed']
                outcomes[name]['physical_evaluations'] = result['physical_evaluations']
                if result.get('passed'):
                    assert result['physical_evaluations'] == 1 and result['accepted_fit_covariance'] is False
                    assert result['native']['sha256'] == j['native']['sha256'] and result['solver']['sha256'] == j['solver']['sha256']
                    for profile in result['comparison']['profiles']:
                        assert profile['segment_seconds'] in (3600,14400)
                        assert profile['covariance_relative_error'] < 1e-8
                        assert [t['damping'] for t in profile['trials']] == [0.,.001,1000.]
                        for trial in profile['trials']:
                            assert trial['maximum_map_discrepancy_posterior_sd'] < 1e-7
                            assert trial['normalized_residual_energy_difference'] < 2e-12
                            assert trial['normalized_orthogonal_residual_energy_difference'] < 2e-12
                if s['status'] == 'completed': assert s['returncode'] == 0 and result['passed'] is True
            else:
                assert s['status'] == 'failed'
    if j['status'] == 'completed':
        assert names == NAMES and all(s['status'] == 'completed' and s['returncode'] == 0 for s in j['steps'])
    for key in ('native','solver'):
        if key in j: assert sha(j[key]['path']) == j[key]['sha256']
    if 'build_manifest' in j:
        assert sha(j['build_manifest']['path']) == j['build_manifest']['sha256']
        b = json.loads(Path(j['build_manifest']['path']).read_text())
        assert b['executable_sha256'] == j['native']['sha256'] and b['upstream_commit'] == '7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee'
        assert b['segmented_extension']['schema'] == 'orbit-poc-segmented-extension-v1'
        for name,h in b['segmented_extension']['files'].items(): assert source['groops/extension/'+name] == h
    files = []
    for folder in ('control','run'):
        files += [x for x in (R/folder).iterdir() if x.is_file() and x.suffix in ('.json','.xml','.log','.txt','.py')]
    files += [x for x in (R/'binaries').iterdir() if x.is_file() and x.suffix == '.json']
    for method in ('pulses','log_drag_ou'):
        folder = R/'run'/('native-linearization-'+method)
        if folder.exists():
            files += [x for x in folder.iterdir() if x.is_file() and x.suffix in ('.json','.log')]
            comparison = folder/'comparison'
            if comparison.exists():
                files += [x for x in comparison.rglob('*') if x.is_file() and x.suffix in ('.json','.npz') and 'solves' not in x.parts]
    files = sorted(set(files))
    assert sum(x.stat().st_size for x in files) < 32*1024*1024
    out = R/'staging/terminal-audit-01';out.mkdir(parents=True,exist_ok=False)
    artifacts = {str(x.relative_to(R)):{'sha256':sha(x),'bytes':x.stat().st_size} for x in files}
    receipt = {'schema':'orbit-poc-segmented-engineering-independent-terminal-audit-v2',
        'evidence_audit':'passed','run_status':j['status'],'engineering_only':True,'release_ready':False,
        'source_sha256':EXPECTED_SOURCE,'source_file_count':372,'native':j.get('native'),'solver':j.get('solver'),
        'pipeline_sha256':sha(R/'run/pipeline.json'),'outcomes':outcomes,'cleanup_verified':True,'artifacts':artifacts,
        'limitations':['Untimed engineering validation; no v4 release or scientific superiority claim.',
            'One-hour fixture has no interior1h/4h cut; shifted-cut and longer-arc evidence remain separate.',
            'Snapshot predates the actual-row GTSAM and shifted-cut Python validation additions.']}
    (out/'audit.json').write_text(json.dumps(receipt,indent=2)+'\n')
    archive = out/'compact.tar.gz'
    with tarfile.open(archive,'w:gz') as t:
        for x in files: t.add(x,arcname=str(x.relative_to(R)),recursive=False)
        t.add(out/'audit.json',arcname='audit.json',recursive=False)
    print(json.dumps({'archive':str(archive),'sha256':sha(archive),'bytes':archive.stat().st_size,
                      'audit_sha256':sha(out/'audit.json'),'files':len(files),'run_status':j['status']}))

if __name__ == '__main__': main()
