from pathlib import Path
from types import SimpleNamespace
from dataclasses import make_dataclass, asdict
import ast, datetime, hashlib, json, os

C = Path('/mnt/d/orbit-segmented-v4/control')
B = Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume/benchmark-01')
REC = B.parent / 'recovery-20261016-01'
def read(p): return json.loads(Path(p).read_bytes())
def pin(p): return {'path': str(p), 'sha256': hashlib.sha256(Path(p).read_bytes()).hexdigest()}
def verify(r):
    p = Path(r['path']); assert pin(p)['sha256'] == r['sha256']; return p
def canonical(v): return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
manifest = read(B / 'manifest.json')
proposal = read(C / 'original150-interrupted-append-proposal01/proposal.json')
assert pin(B / 'manifest.json') == proposal['manifest']
config = read(verify(proposal['configuration']))
source = verify(proposal['archived_protocol'])
nodes = {x.name:x for x in ast.parse(source.read_text()).body if isinstance(x,ast.FunctionDef)}
module = ast.Module(body=[nodes['attempt_job'],nodes['verify_checkpoint']], type_ignores=[])
ast.fix_missing_locations(module)
ns = {'read_json':read, 'verify_artifact':verify, 'canonical_hash':canonical, 'asdict':asdict,
      'validate_complete_result':lambda *_: (_ for _ in ()).throw(AssertionError('No complete fit expected'))}
exec(compile(module, str(source), 'exec'), ns)
controls = make_dataclass('Controls', [(k,object) for k in config['controls']])
cfg = SimpleNamespace(controls=controls(**config['controls']))
cases = {x['case_id']:x for x in manifest['cases']}
prior = read(C / 'original150-seven-prefix-independent-review01.json')
prefix = []
for a in manifest['attempts'][:8]:
    d = B / 'attempts' / a['attempt_id']
    job = ns['attempt_job'](cfg, manifest, cases[a['case_id']], a)
    result = ns['verify_checkpoint'](d, job)
    prefix.append({'attempt_id':a['attempt_id'], 'profile':a['profile'], 'status':result['status'],
                   'result':pin(d/'result.json'), 'index':pin(d/'result-record.json')})
assert prefix[:7] == prior['terminal_prefix']
assert [x['status'] for x in prefix] == ['failed','timeout','timeout','timeout','timeout','failed','interrupted','failed']
d = B / 'attempts' / manifest['attempts'][7]['attempt_id']
result = read(d / 'result.json')
assert result['converged'] is result['covariance_valid'] is False
assert result['native_binary_sha256'] == manifest['legacy_runtime']['native']['sha256'] == '74863d5a16dbcb1f762e9a4bbe7eebc064e1d11f641691a7d3f87e3669288453'
assert result['harness_execution']['runtime'] == manifest['legacy_runtime']
assert result['harness_execution']['returncode'] == 0 and result['harness_execution']['resource_limit_status'] is None
for x in result['artifacts']: verify(x)
preservation = read(d / 'legacy-terminal-preservation.json')
assert preservation['archived_runtime_modified'] is False and preservation['removed'] == [] and preservation['removed_bytes'] == 0
assert preservation['terminal_status'] == 'failed' and preservation['request_hash'] == result['request_hash']
verify(preservation['helper']); verify(preservation['control_plan'])
assert preservation['helper']['sha256'] == 'bb23360e9cd9af6219e6771fca90c834288f9467e3f1f55b38eca8552fd49c61'
native = read(d / 'native_runtime.json')
assert [x['returncode'] for x in native['execution']] == [0,1]
for x in native['execution']:
    assert pin(x['command'][1])['sha256'] == x['config_sha256']
    assert x['native_binary_sha256'] == result['native_binary_sha256'] and x['blas_openmp_threads'] == 1 and x['timed_out'] is False
log = d / 'iteration-01/estimate.log'
assert '(cholesky)' in log.read_text() and 'cannot compute decomposition, error = 429' in log.read_text()
boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert boot == '04656a53-958c-4419-8605-c7088e036b9f'
def proc(pid):
    p=Path('/proc')/str(pid); f=(p/'stat').read_text().rsplit(')',1)[1].split()
    return {'pid':pid,'parent':int(f[1]),'start_ticks':int(f[19]),'state':f[0],
            'argv':[x.decode() for x in (p/'cmdline').read_bytes().split(b'\0') if x],
            'affinity':sorted(os.sched_getaffinity(pid))}
live = [proc(x) for x in [9877,9878,9879]]
assert [x['start_ticks'] for x in live] == [465866,465929,465981]
assert live[1]['parent']==9877 and live[2]['parent']==9878 and live[2]['affinity']==[30]
assert live[2]['argv']==read(C/'original150-adapter03-independent-review01/review.json')['live_owned_processes'][2]['argv']
allp={}
for p in Path('/proc').iterdir():
    if p.name.isdecimal():
        try: allp[int(p.name)]=proc(int(p.name))
        except (FileNotFoundError,ProcessLookupError,PermissionError): pass
owned={9879}
while True:
    more={pid for pid,v in allp.items() if v['parent'] in owned}
    if more <= owned: break
    owned |= more
desc=[allp[x] for x in sorted(owned-{9879})]
ninth=B/'attempts'/manifest['attempts'][8]['attempt_id']
assert (ninth/'request.json').exists() and not (ninth/'result-record.json').exists()
expected=ns['attempt_job'](cfg,manifest,cases[manifest['attempts'][8]['case_id']],manifest['attempts'][8])
assert read(ninth/'request.json')==expected
assert any(str(ninth/'worker-request.json') in v['argv'] for v in desc)
assert all(v['affinity']==[30] for v in desc)
assert not any((B/'attempts'/a['attempt_id']/'result-record.json').exists() for a in manifest['attempts'][8:])
for a in manifest['attempts'][9:]: assert not (B/'attempts'/a['attempt_id']).exists()
out=C/'original150-eighth-terminal-independent-review01.json'
value={'schema':'orbit-poc-original150-eighth-terminal-independent-review-v1','passed':True,
       'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'helper':pin(Path(__file__)),
       'prior_seven_review':pin(C/'original150-seven-prefix-independent-review01.json'),
       'terminal_prefix':prefix,'terminal_attempts':8,'eighth_preservation':pin(d/'legacy-terminal-preservation.json'),
       'native_failure_log':pin(log),'harness_elapsed_seconds':result['harness_execution']['elapsed_seconds'],
       'peak_process_tree_rss_bytes':result['harness_execution']['peak_process_tree_rss_bytes'],
       'native_binary_sha256':result['native_binary_sha256'],'boot_id':boot,'live_control_chain':live,
       'live_ninth_descendants':desc,'ninth_request':pin(ninth/'request.json'),
       'scope':'Read-only compact checkpoint and ownership audit. Eight actual terminal outcomes are preserved; the ninth frozen QR legacy-Jacobian attempt is active on CPU30. No full dataset/runtime rescan, numerical replacement, retry, launch, or completion claim.'}
with out.open('x') as f: json.dump(value,f,indent=2,sort_keys=True); f.write('\n')
print(json.dumps(pin(out)))
