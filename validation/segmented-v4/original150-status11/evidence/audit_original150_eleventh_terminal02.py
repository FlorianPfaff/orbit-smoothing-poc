"""Read-only extension of the tenth-checkpoint audit; no estimator or campaign writes."""
from pathlib import Path
from types import SimpleNamespace
from dataclasses import make_dataclass, asdict
import ast, datetime, hashlib, json, os
C=Path('/mnt/d/orbit-segmented-v4/control')
B=Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume/benchmark-01')
REC=B.parent/'recovery-20261016-01'
def read(p):return json.loads(Path(p).read_bytes())
def digest(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for x in iter(lambda:f.read(4*1024*1024),b''):h.update(x)
 return h.hexdigest()
def pin(p):return {'path':str(p),'sha256':digest(p)}
def canonical(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
resolutions=[]
def audit_path(path):
 p=Path(path)
 if p.exists():return p
 q=Path('/proc/9879/root')/str(p).lstrip('/')
 assert q.is_file(),str(p)
 if str(p).startswith('/mnt/seagate10tb/'):
  backing=Path('/mnt/d/orbit-numerics-v3.1-mirror/remote-root')/str(p).lstrip('/')
  assert os.path.samefile(q,backing)
 else:backing=None
 row={'canonical_path':str(p),'actual_namespace_path':str(q),'backing_path':None if backing is None else str(backing)}
 if row not in resolutions:resolutions.append(row)
 return q
def verify(r):
 p=audit_path(r['path']);assert digest(p)==r['sha256'],r['path'];return p
prior_path=C/'original150-tenth-terminal-independent-review01.json'
assert digest(prior_path)=='2038256650e3fbde12c40ce342e02b59c61274e89d71a0a8abea3778bbb9df71'
prior=read(prior_path);assert prior['passed'] and prior['terminal_attempts']==10
verify(prior['helper']);verify(prior['archived_protocol']);verify(prior['archived_comparison_protocol']);verify(prior['original_namespace_wrapper'])
proposal=read(C/'original150-interrupted-append-proposal01/proposal.json')
assert verify(proposal['manifest'])==B/'manifest.json'
manifest=read(B/'manifest.json');config=read(verify(proposal['configuration']))
source=verify(proposal['archived_protocol']);runtime=manifest['new_runtime']
assert runtime['source_sha256']==manifest['source']['sha256']=='553ad084a7165b045f8f1f9eb9abfaac4df8833d2038595f622def468fcdebae'
assert runtime['native']['sha256']=='3aad854b51102dce1fa7a8622177b33075d928d060cb10d740f1b137a00c33e9'
# Rehash the native executable and directly declared Python/library pins, not full environment trees.
for record in [runtime['native'],runtime['python'],runtime['supplemental_sources'],*runtime['libraries']['files']]:verify(record)
for relative in ['src/orbit_poc/numerics/backend.py','src/orbit_poc/numerics/protocol.py','src/orbit_poc/numerics/retention.py','src/orbit_poc/numerics/optimizer.py']:
 verify({'path':str(Path(runtime['source_root'])/relative),'sha256':manifest['source']['files'][relative]})
adapter_path=REC/'campaign-adapter03.json';adapter=read(adapter_path)
assert adapter['source_sha256']==runtime['source_sha256']
for key in ['helper','plan','retention_module','startup_receipt']:verify(adapter[key])
assert adapter['helper']['sha256']=='bb23360e9cd9af6219e6771fca90c834288f9467e3f1f55b38eca8552fd49c61'
startup=read(verify(adapter['startup_receipt']));assert startup['status']=='verified'
assert all(startup['configuration'][k]==proposal['configuration'][k] for k in ('path','sha256'))
# Original function AST is executed unchanged, with read-only artifact verification.
nodes={x.name:x for x in ast.parse(source.read_text()).body if isinstance(x,ast.FunctionDef)}
module=ast.Module(body=[nodes[n] for n in ('attempt_job','verify_checkpoint')],type_ignores=[]);ast.fix_missing_locations(module)
ns={'read_json':read,'verify_artifact':verify,'canonical_hash':canonical,'asdict':asdict}
exec(compile(module,str(source),'exec'),ns)
controls=make_dataclass('Controls',[(k,object) for k in config['controls']]);cfg=SimpleNamespace(controls=controls(**config['controls']))
cases={x['case_id']:x for x in manifest['cases']}
prefix=[]
for a,old in zip(manifest['attempts'][:10],prior['terminal_prefix']):
 d=B/'attempts'/a['attempt_id'];verify(old['result']);verify(old['index'])
 job=ns['attempt_job'](cfg,manifest,cases[a['case_id']],a)
 assert read(d/'request.json')==job
 assert read(d/'result-record.json')['request_hash']==canonical(job)
 prefix.append(old)
a=manifest['attempts'][10];d=B/'attempts'/a['attempt_id'];case=cases[a['case_id']]
job=ns['attempt_job'](cfg,manifest,case,a)
assert a['attempt_id']=='retained-pulse-neighbor-300001--qr_lm_legacy_jacobian'
assert read(d/'request.json')==read(d/'worker-request.json')==job
assert pin(d/'request.json')==prior['eleventh_request']
assert canonical(case['input_inventory'])==case['input_manifest_hash']==job['input_manifest_hash']
assert job['estimation_inputs']==case['fit_request']['estimation_inputs']
result=ns['verify_checkpoint'](d,job);execution=result['harness_execution']
assert result['status']=='timeout' and result['converged'] is result['covariance_valid'] is False
assert result['numerics_manifest_hash']==manifest['manifest_hash'] and result['input_manifest_hash']==case['input_manifest_hash']
assert execution['runtime']==runtime and execution['resource_limit_status']=='timeout'
assert execution['elapsed_seconds']>=7200 and execution['returncode']==-15 and execution['process_group_isolated'] is True
assert execution['pid']==28272
verify(execution['log'])
retention=read(d/'retention.json')
assert retention['status']=='complete' and retention['terminal_status']=='timeout' and retention['errors']==[]
assert retention['removed']==[] and retention['removed_bytes']==0 and retention['archived_runtime_modified'] is False
assert all(x.get('metadata',{}).get('accepted_covariance') is False for x in result['artifacts'] if x['role']!='numerical_retention_audit')
selected=[]
for item in case['input_inventory']:
 if item['role'] in ('gnss_observations','bootstrap_orbit','nominal_initialization','fixed_initial_state','closed_nominal_orbit') or Path(item['path']).name=='native_preparation.json':
  verify(item);selected.append(item)
prefix.append({'attempt_id':a['attempt_id'],'profile':a['profile'],'status':result['status'],'result':pin(d/'result.json'),'index':pin(d/'result-record.json')})
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==prior['boot_id']
def proc(pid):
 p=Path('/proc')/str(pid);f=(p/'stat').read_text().rsplit(')',1)[1].split()
 return {'pid':pid,'parent':int(f[1]),'process_group':int(f[2]),'session':int(f[3]),'start_ticks':int(f[19]),'state':f[0],'argv':[x.decode() for x in (p/'cmdline').read_bytes().split(b'\0') if x],'affinity':sorted(os.sched_getaffinity(pid))}
live=[proc(x['pid']) for x in prior['live_control_chain']]
for row,old in zip(live,prior['live_control_chain']):
 for key in ('pid','parent','start_ticks','argv','affinity'):assert row[key]==old[key],(key,row['pid'])
 assert row['state']!='Z'
allp={}
for p in Path('/proc').iterdir():
 if p.name.isdecimal():
  try:allp[int(p.name)]=proc(int(p.name))
  except (FileNotFoundError,ProcessLookupError,PermissionError):pass
cleanup=[]
for old in prior['live_eleventh_descendants']:
 current=allp.get(old['pid']);same=current is not None and current['start_ticks']==old['start_ticks']
 assert not same or current['state']=='Z'
 cleanup.append({'prior_identity':old,'observation':current,'status':'absent' if current is None else 'zombie_non_live' if same else 'pid_reused_not_original'})
nonlive_group=[x for x in allp.values() if x['process_group']==execution['pid']]
assert all(x['state']=='Z' for x in nonlive_group)
owned={9879}
while True:
 more={pid for pid,v in allp.items() if v['parent'] in owned}
 if more<=owned:break
 owned|=more
desc=[allp[x] for x in sorted(owned-{9879})];assert desc
next_a=manifest['attempts'][11];next_d=B/'attempts'/next_a['attempt_id']
assert next_a['attempt_id']=='retained-pulse-neighbor-300001--qr_lm_staged_jacobian'
next_job=ns['attempt_job'](cfg,manifest,cases[next_a['case_id']],next_a)
assert read(next_d/'request.json')==read(next_d/'worker-request.json')==next_job
assert not (next_d/'result-record.json').exists() and not (next_d/'result.json').exists()
workers=[x for x in desc if str(next_d/'worker-request.json') in x['argv']]
assert len(workers)==1 and workers[0]['parent']==9879
assert workers[0]['process_group']==workers[0]['session']==workers[0]['pid']
assert str(Path(runtime['source_root'])) in workers[0]['argv']
assert all(x['affinity']==[30] for x in desc)
natives=[x for x in desc if x['argv'] and x['argv'][0]==runtime['native']['path']]
assert len(natives)==1 and natives[0]['parent']==workers[0]['pid']
assert natives[0]['argv'][1].startswith(str(next_d)+'/') and natives[0]['argv'][1].endswith('.xml')
assert os.path.samefile(Path('/proc')/str(natives[0]['pid'])/'exe',Path(runtime['native']['path']))
thread_env={}
for x in [workers[0],natives[0]]:
 values=dict(v.split(b'=',1) for v in (Path('/proc')/str(x['pid'])/'environ').read_bytes().split(b'\0') if b'=' in v)
 found={k:values[k.encode()].decode() for k in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'] if k.encode() in values}
 assert found and all(v=='1' for v in found.values())
 thread_env[str(x['pid'])]=found
lock_rows=[line for line in Path('/proc/locks').read_text().splitlines() if ' WRITE 9879 ' in line]
lock_evidence=[]
for name in ['controller/numerics.lock','numerics.lock']:
 path=B/name;s=path.stat();dev=f'{os.major(s.st_dev):02x}:{os.minor(s.st_dev):02x}:{s.st_ino}'
 matches=[line for line in lock_rows if dev in line];assert len(matches)==1
 fds=[]
 for fd in Path('/proc/9879/fd').iterdir():
  try:
   if os.path.samefile(fd,path):fds.append(fd.name)
  except (OSError,FileNotFoundError):pass
 assert fds
 lock_evidence.append({'path':str(path),'device':s.st_dev,'inode':s.st_ino,'owned_fds':fds,'proc_lock':matches[0]})
for other in manifest['attempts'][12:]:assert not (B/'attempts'/other['attempt_id']).exists()
assert [proc(x['pid'])['start_ticks'] for x in live]==[x['start_ticks'] for x in live]
assert proc(workers[0]['pid'])['start_ticks']==workers[0]['start_ticks']
assert not (next_d/'result-record.json').exists()
value={'schema':'orbit-poc-original150-eleventh-terminal-independent-review-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'helper':pin(__file__),'preserved_prior_author_check':{'helper':pin(C/'audit_original150_eleventh_terminal01.py'),'log':pin(C/'original150-eleventh-terminal-independent-review01.log'),'reason':'Initial audit compared complete pin dictionaries; the proposal additionally records bytes. Version02 compares identical path and SHA256, retaining all prior byte checks.'},'prior_ten_review':pin(prior_path),'manifest':pin(B/'manifest.json'),'configuration':proposal['configuration'],'archived_protocol':pin(source),'original_namespace_wrapper':prior['original_namespace_wrapper'],'campaign_adapter':pin(adapter_path),'startup_receipt':adapter['startup_receipt'],'runtime':runtime,'terminal_prefix':prefix,'terminal_attempts':11,'status_counts':{k:sum(x['status']==k for x in prefix) for k in ('failed','timeout','complete','interrupted')},'eleventh':{'request':pin(d/'request.json'),'worker_request':pin(d/'worker-request.json'),'result':pin(d/'result.json'),'index':pin(d/'result-record.json'),'retention':pin(d/'retention.json'),'resource_guard':pin(d/'resource-guard.json'),'elapsed_seconds':execution['elapsed_seconds'],'peak_process_tree_rss_bytes':execution['peak_process_tree_rss_bytes'],'returncode':execution['returncode'],'accepted_covariance':False,'artifacts':result['artifacts'],'input_manifest_hash':case['input_manifest_hash'],'exact_input_inventory_records':len(case['input_inventory']),'selected_input_bytes_reverified':selected,'input_scope':'Exact frozen job, full input-inventory declaration hash and six selected observation/initialization metadata or payload pins verified. Complete frozen input/runtime trees inherit the sealed startup receipt; no bulk rehash was repeated.'},'boot_id':boot,'eleventh_known_identity_cleanup':cleanup,'eleventh_process_group_members':nonlive_group,'cleanup_scope':'Known worker/native identities and every current member of the isolated worker process group are absent or zombie/non-live. This observation is not an invented controller cleanup receipt or proof of earlier intermediate process membership.','live_control_chain':live,'live_twelfth_descendants':desc,'live_thread_environment':thread_env,'owned_locks':lock_evidence,'twelfth_request':pin(next_d/'request.json'),'twelfth_worker_request':pin(next_d/'worker-request.json'),'remaining_unstarted_after_twelfth':138,'canonical_artifact_resolution':resolutions,'scope':'Read-only new checkpoint/artifact verification, exact frozen identity, retained-failure evidence and timestamped ownership audit. First ten result/index bytes are unchanged and their previous independent audit is retained without rereading their large artifacts. Twelfth is active, not complete. The one completed legacy result uses archived legacy criteria, not corrected v3.1/V4 strict convergence. No retry, estimator execution, campaign mutation, full campaign completion or V4 release claim.'}
out=C/'original150-eleventh-terminal-independent-review02.json'
with out.open('x') as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n')
print(json.dumps(pin(out)))
