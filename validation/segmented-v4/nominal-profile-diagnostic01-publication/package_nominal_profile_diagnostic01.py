#!/usr/bin/env python3
"""Publish only audited compact replay evidence; retain arrays outside Git."""
from pathlib import Path
import base64, datetime, hashlib, html, json, subprocess

CONTROL=Path('/mnt/d/orbit-segmented-v4/control')
OUT=Path('/mnt/d/orbit-segmented-v4/publication-nominal-profile-diagnostic01')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text())
def pin(p): return {'path':str(p),'sha256':sha(p),'bytes':Path(p).stat().st_size}
def put(rel, payload):
    p=OUT/rel; p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as stream: stream.write(payload)
def write(rel, payload): put(rel,(json.dumps(payload,indent=2,sort_keys=True)+'\n').encode())

assert not OUT.exists(); OUT.mkdir()
review=read(CONTROL/'nominal-profile-diagnostic01-terminal-independent-review/review.json')
back=read(CONTROL/'nominal-profile-diagnostic01-terminal-independent-review/readback.json')
assert review['passed'] and back['passed'] and review['fit_attempts']==0
assert review['final_position_change_m']==1.1519824039985408e-8
local=[
    'nominal-profile-diagnostic01-terminal-independent-review/review.json',
    'nominal-profile-diagnostic01-terminal-independent-review/readback.json',
    'nominal-profile-diagnostic01-independent-review/review.json',
    'nominal-profile-diagnostic01-staging.json',
    'audit_nominal_profile_diagnostic_terminal01.py',
    'audit_nominal_profile_diagnostic01.py',
    'replay_nominal_profile01.py','run_nominal_profile01.py',
    'test_replay_nominal_profile01.py',
    'nominal-profile-diagnostic01-independent-tests.log',
    'nominal-profile-diagnostic01-independent-tests.xml']
sources=[]
for name in local:
    p=CONTROL/name; put('provenance/'+name,p.read_bytes())
    sources.append({'relative':'provenance/'+name,'source':pin(p)})
remote=[]
for key in ('pipeline','plan','result'):
    remote.append({'relative':'raw/'+key+'.json',**review[key]})
for iteration in back['independently_recomputed_iterations']:
    for record in iteration['artifacts']:
        name=Path(record['path']).name
        if name in {'propagate.xml','propagate.execution.json','propagate.log','derivatives.json'}:
            remote.append({'relative':f"raw/iteration-{iteration['iteration']:02d}/"+name,**record})
payload=base64.b64encode(json.dumps(remote).encode()).decode()
script="""import base64,hashlib,json,pathlib
entries=json.loads(base64.b64decode(%r)); result=[]
for entry in entries:
 p=pathlib.Path(entry['path']); b=p.read_bytes()
 assert not p.is_symlink() and len(b)<1000000 and hashlib.sha256(b).hexdigest()==entry['sha256']
 result.append(dict(entry,bytes=len(b),base64=base64.b64encode(b).decode()))
print(json.dumps(result))
""" % payload
r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','python3 -'],
    input=script,text=True,capture_output=True,timeout=45)
assert r.returncode==0,r.stderr
for item in json.loads(r.stdout):
    b=base64.b64decode(item.pop('base64')); assert hashlib.sha256(b).hexdigest()==item['sha256']
    rel=item.pop('relative'); put(rel,b); sources.append({'relative':rel,'source':item})
result=read(OUT/'raw/result.json'); pipeline=read(OUT/'raw/pipeline.json')
assert result['status']=='closed' and result['converged'] is True
assert pipeline['status']=='passed_diagnostic' and pipeline['final_cleanup']['verified']
assert len(result['iterations'])==2
for actual,recomputed in zip(result['iterations'],back['independently_recomputed_iterations']):
    for k in ('maximum_position_change_m','maximum_velocity_change_m_s'):
        assert actual[k]==recomputed[k]
    assert actual['maximum_initial_state_error_si']==[0]*6
status={'schema':'orbit-poc-nominal-profile-diagnostic-publication-v1',
    'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':True,
    'fit_attempts':0,'release_ready':False,'native':result['native'],
    'profile_delta':result['algorithm_delta'],'telemetry_delta':result['telemetry_delta'],
    'fixed_initial_state_exact':True,'iterations':2,
    'position_tolerance_m':result['position_tolerance_m'],
    'velocity_tolerance_m_s':result['velocity_tolerance_m_s'],
    'maximum_iterations':result['maximum_iterations'],
    'final_position_change_m':review['final_position_change_m'],
    'final_velocity_change_m_s':review['final_velocity_change_m_s'],
    'sources':sources,'independent_audit':'provenance/nominal-profile-diagnostic01-terminal-independent-review/review.json',
    'scope':'Exact fixed-initial-state replay of the failed 48-hour synthetic preparation, not a production preparation or benchmark fit.',
    'limitations':['The existing corrected profile contains multiple numerical changes; this replay isolates profile selection, not each internal change.',
        'Full new preparation, nonlinear fit gates, all 68 benchmark attempts and the original 150-attempt report remain required.',
        'Failed preparation evidence is retained separately; no thresholds, input bytes or native executable were changed.']}
write('status.json',status)
rows=''.join(f"<tr><td>{e['iteration']}</td><td>{e['maximum_position_change_m']:.17g}</td><td>{e['maximum_velocity_change_m_s']:.17g}</td><td>{str(e['closed']).lower()}</td></tr>" for e in result['iterations'])
page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>48-hour preparation profile diagnostic</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:950px;margin:3rem auto;padding:0 1.5rem;color:#162338}table{border-collapse:collapse;width:100%}td,th{padding:.6rem;text-align:left;border-bottom:1px solid #ccc}.status{padding:1rem;background:#e6f2ed;border-left:4px solid #3a7655}a{color:#134f9e}</style><h1>The corrected synthetic profile closes the exact failed 48-hour initialization</h1><p class="status">The controlled replay passed independent audit after two iterations. Final trajectory changes were 11.5 nm in position and 1.25×10⁻¹¹ m/s in velocity, below the unchanged 2 µm and 3×10⁻⁹ m/s limits.</p><p>The original six-state target, initial orbit, physical inputs and native executable were retained. The only algorithm selection changed from the omitted default <code>legacy_v3</code> to <code>synthetic_complete_v1</code>. Diagnostic output paths were added and output paths rebound to a separate directory. The initial state was restored exactly on both iterations.</p><table><thead><tr><th>Iteration</th><th>Maximum position change (m)</th><th>Maximum velocity change (m/s)</th><th>Closed</th></tr></thead><tbody>'''+rows+'''</tbody></table><p>This supports the targeted V4 preparation configuration correction. It does not isolate which individual internal arithmetic or derivative change in the corrected profile is necessary. The failed legacy-profile preparation remains preserved.</p><p><strong>V4 still has 0/68 benchmark fits.</strong> This is an initialization diagnostic, not estimator convergence, covariance validation or release readiness. A new preparation run and all remaining release gates are required.</p><ul><li><a href="status.json">Status, provenance and scope</a></li><li><a href="manifest.json">Exact publication manifest</a></li><li><a href="raw/result.json">Actual diagnostic result</a></li><li><a href="raw/pipeline.json">Owned-process execution and cleanup</a></li><li><a href="provenance/nominal-profile-diagnostic01-terminal-independent-review/review.json">Independent actual-result audit</a></li><li><a href="provenance/nominal-profile-diagnostic01-terminal-independent-review/readback.json">Independent recomputation and retained payload hashes</a></li><li><a href="../status-preparation-original150-03/index.html">Preserved failure evidence</a></li></ul></html>'''
put('index.html',page.encode())
entries=[{'relative':str(p.relative_to(OUT)),**{k:v for k,v in pin(p).items() if k!='path'}} for p in sorted(OUT.rglob('*')) if p.is_file()]
write('manifest.json',{'schema':'orbit-poc-compact-diagnostic-publication-manifest-v1','entries':entries,
    'files':len(entries),'bytes':sum(x['bytes'] for x in entries),'helper':pin(__file__),'release_ready':False})
for item in entries: assert sha(OUT/item['relative'])==item['sha256']
print(json.dumps({'root':str(OUT),'manifest':pin(OUT/'manifest.json'),'files':len(entries)}))
