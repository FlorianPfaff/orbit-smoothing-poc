from pathlib import Path
from types import SimpleNamespace
from dataclasses import make_dataclass, asdict
import ast, datetime, hashlib, json, os, re, numpy as np

C = Path('/mnt/d/orbit-segmented-v4/control')
B = Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume/benchmark-01')
REC = B.parent / 'recovery-20261016-01'
def read(p): return json.loads(Path(p).read_bytes())
def pin(p): return {'path': str(p), 'sha256': hashlib.sha256(Path(p).read_bytes()).hexdigest()}
namespace_resolutions=[]
def audit_path(path):
    p=Path(path)
    if p.exists():return p
    q=Path('/proc/9879/root')/str(p).lstrip('/')
    assert q.is_file(),p
    if str(p).startswith('/mnt/seagate10tb/'):
        backing=Path('/mnt/d/orbit-numerics-v3.1-mirror/remote-root')/str(p).lstrip('/')
        assert os.path.samefile(q,backing)
    else:backing=None
    row={'canonical_path':str(p),'actual_namespace_path':str(q),'backing_path':None if backing is None else str(backing)}
    if row not in namespace_resolutions:namespace_resolutions.append(row)
    return q
def verify(r):
    p = audit_path(r['path']); assert pin(p)['sha256'] == r['sha256']; return p
def canonical(v): return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
manifest = read(B / 'manifest.json')
proposal = read(C / 'original150-interrupted-append-proposal01/proposal.json')
assert verify(proposal['manifest']) == B / 'manifest.json'
config = read(verify(proposal['configuration']))
source = verify(proposal['archived_protocol'])
nodes = {x.name:x for x in ast.parse(source.read_text()).body if isinstance(x,ast.FunctionDef)}
module = ast.Module(body=[nodes[name] for name in ('attempt_job','verify_checkpoint','validate_complete_result','read_cartesian_estimate')], type_ignores=[])
ast.fix_missing_locations(module)
ns = {'read_json':read, 'verify_artifact':verify, 'canonical_hash':canonical, 'asdict':asdict,
      'Path':audit_path,'file_hash':lambda p:pin(p)['sha256'],'is_digest':lambda x:isinstance(x,str) and re.fullmatch('[0-9a-f]{64}',x) is not None}
comparison=source.parents[1]/'comparison/protocol.py'
ct=ast.parse(comparison.read_text());cn={n.name:n for n in ct.body if isinstance(n,ast.FunctionDef)}
cm=ast.Module(body=[cn['_verify_artifacts'],cn['validate_fit_result']],type_ignores=[]);ast.fix_missing_locations(cm)
exec(compile(cm,str(comparison),'exec'),ns)
exec(compile(module, str(source), 'exec'), ns)
wrapper=Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/with_local_mirror_d_output.py')
assert pin(wrapper)['sha256']=='9c39280813adcc0080f92aab5f0b91d0f60b9ce38b2c0e51f9d8bf6eea7f3578'

controls = make_dataclass('Controls', [(k,object) for k in config['controls']])
cfg = SimpleNamespace(controls=controls(**config['controls']))
cases = {x['case_id']:x for x in manifest['cases']}
prior = read(C / 'original150-eighth-terminal-independent-review02.json')
prefix = []
for a in manifest['attempts'][:10]:
    d = B / 'attempts' / a['attempt_id']
    job = ns['attempt_job'](cfg, manifest, cases[a['case_id']], a)
    result = ns['verify_checkpoint'](d, job)
    prefix.append({'attempt_id':a['attempt_id'], 'profile':a['profile'], 'status':result['status'],
                   'result':pin(d/'result.json'), 'index':pin(d/'result-record.json')})
assert prefix[:8] == prior['terminal_prefix']
assert [x['status'] for x in prefix] == ['failed','timeout','timeout','timeout','timeout','failed','interrupted','failed','timeout','complete']
ninth_dir=B/'attempts'/manifest['attempts'][8]['attempt_id'];ninth_result=read(ninth_dir/'result.json')
assert ninth_result['converged'] is ninth_result['covariance_valid'] is False
assert ninth_result['harness_execution']['runtime']==manifest['new_runtime']
assert ninth_result['harness_execution']['resource_limit_status']=='timeout' and ninth_result['harness_execution']['elapsed_seconds']>=7200
assert manifest['new_runtime']['native']['sha256']=='3aad854b51102dce1fa7a8622177b33075d928d060cb10d740f1b137a00c33e9'
d = B / 'attempts' / manifest['attempts'][9]['attempt_id'];result=read(d/'result.json')
assert result['converged'] is result['covariance_valid'] is True and result['covariance_scope']=='marginalized'
assert result['native_binary_sha256']==manifest['legacy_runtime']['native']['sha256']=='74863d5a16dbcb1f762e9a4bbe7eebc064e1d11f641691a7d3f87e3669288453'
assert result['harness_execution']['runtime']==manifest['legacy_runtime']
assert result['harness_execution']['returncode']==0 and result['harness_execution']['resource_limit_status'] is None
preservation=read(d/'legacy-terminal-preservation.json')
assert preservation['archived_runtime_modified'] is False and preservation['removed']==[] and preservation['removed_bytes']==0
assert preservation['terminal_status']=='complete' and preservation['request_hash']==result['request_hash']
verify(preservation['helper']);verify(preservation['control_plan'])
assert preservation['helper']['sha256']=='bb23360e9cd9af6219e6771fca90c834288f9467e3f1f55b38eca8552fd49c61'
native=read(d/'native_runtime.json');assert len(native['execution'])>1
for x in native['execution']:
    assert x['returncode']==0 and pin(x['command'][1])['sha256']==x['config_sha256']
    assert x['native_binary_sha256']==result['native_binary_sha256'] and x['blas_openmp_threads']==1 and x['timed_out'] is False
est=[a for a in result['artifacts'] if a['role']=='state_estimate'];assert len(est)==1
arrays=ns['read_cartesian_estimate'](est[0]);cov=arrays['covariance'];sd=np.sqrt(np.diagonal(cov,axis1=1,axis2=2));cor=cov/sd[:,:,None]/sd[:,None,:]
state_summary={'epochs':len(arrays['mjd']),'state_shape':list(arrays['states'].shape),'covariance_shape':list(cov.shape),'finite_ordered_cartesian':True,'normalized_covariance_minimum_eigenvalue':float(np.linalg.eigvalsh(cor).min()),'archived_complete_result_validation_passed':True}
assert state_summary['normalized_covariance_minimum_eigenvalue']>0
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
eleventh=B/'attempts'/manifest['attempts'][10]['attempt_id']
assert (eleventh/'request.json').exists() and not (eleventh/'result-record.json').exists()
expected=ns['attempt_job'](cfg,manifest,cases[manifest['attempts'][10]['case_id']],manifest['attempts'][10])
assert read(eleventh/'request.json')==expected
assert any(str(eleventh/'worker-request.json') in v['argv'] for v in desc)
assert all(v['affinity']==[30] for v in desc)
assert not any((B/'attempts'/a['attempt_id']/'result-record.json').exists() for a in manifest['attempts'][10:])
for a in manifest['attempts'][11:]:assert not (B/'attempts'/a['attempt_id']).exists()
# Recheck control ownership after reading the canonical artifact through its already-running namespace.
assert [proc(x)['start_ticks'] for x in [9877,9878,9879]]==[465866,465929,465981]
out=C/'original150-tenth-terminal-independent-review01.json'
value={'schema':'orbit-poc-original150-tenth-terminal-independent-review-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'helper':pin(Path(__file__)),'prior_eight_review':pin(C/'original150-eighth-terminal-independent-review02.json'),'archived_protocol':pin(source),'archived_comparison_protocol':pin(comparison),'original_namespace_wrapper':pin(wrapper),'canonical_artifact_resolution':namespace_resolutions,'terminal_prefix':prefix,'terminal_attempts':10,'status_counts':{k:sum(x['status']==k for x in prefix) for k in ('failed','timeout','complete','interrupted')},'ninth':{'result':pin(ninth_dir/'result.json'),'elapsed_seconds':ninth_result['harness_execution']['elapsed_seconds'],'peak_process_tree_rss_bytes':ninth_result['harness_execution']['peak_process_tree_rss_bytes'],'runtime':manifest['new_runtime']['native']},'tenth':{'result':pin(d/'result.json'),'preservation':pin(d/'legacy-terminal-preservation.json'),'state_estimate':est[0],'state_array_validation':state_summary,'harness_elapsed_seconds':result['harness_execution']['elapsed_seconds'],'peak_process_tree_rss_bytes':result['harness_execution']['peak_process_tree_rss_bytes'],'native_binary_sha256':result['native_binary_sha256'],'convergence_scope':'The archived legacy_v3 protocol and its original criteria. This does not certify corrected v3.1 strict convergence, the v4 objective or v4 release.'},'boot_id':boot,'live_control_chain':live,'live_eleventh_descendants':desc,'eleventh_request':pin(eleventh/'request.json'),'scope':'Read-only exact frozen checkpoint/artifact/Cartesian covariance and live ownership audit. Ten actual terminal outcomes are preserved; eleventh frozen QR legacy-Jacobian attempt is active onCPU30. No full data/runtime rescan, numerical replacement, retry, launch, or campaign completion claim.'}
with out.open('x') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(out)))
