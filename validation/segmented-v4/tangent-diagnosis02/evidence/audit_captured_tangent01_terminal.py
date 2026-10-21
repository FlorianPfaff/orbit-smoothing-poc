from pathlib import Path
import hashlib,json,datetime,importlib.util
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-standalone-01';C=D/'control';O=D/'run/replay'
def pin(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),sha256=h.hexdigest(),bytes=p.stat().st_size)
def read(p):return json.loads(Path(p).read_text())
p=read(C/'plan.json');e=read(C/'execution.json');j=read(C/'pipeline.json');r=read(O/'result.json')
assert pin(C/'plan.json')['sha256']==r['plan_sha256']=='f9730ed02016bfa3e3d6f559df5aa1525ae3a306875a4f817b90db740153a7b6'
assert pin(C/'execution.json')['sha256']==p['execution']['sha256']=='008078a3083dc16b8f0c257a7045175663f48911366a4a4e224f418b89744008'
assert pin(C/'pipeline.json')['sha256']=='78351bd0849df13a34d38cda847e5f4b92056c210fc66fb560e49b9dc5c55865'
assert pin(O/'result.json')['sha256']=='37f1302c0957e8a2ade9dc426361e6feee734a6a80ee1af6ee0b5d0258820435'
assert r['status']=='reader_failed' and r['returncode']==1 and r['groops_propagations']==r['fit_attempts']==0 and r['release_evidence']is False
assert j['status']=='failed_diagnostic' and j['returncode']==1 and j['interrupted_or_timeout']is False and j['final_cleanup']['verified']is True and j['final_cleanup']['errors']==[]
spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
spec=importlib.util.spec_from_file_location('worker',p['worker']['path']);w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
assert len(p['inputs'])==8 and p['inputs']==r['inputs']
for item in p['inputs'].values():assert pin(o.resolved_host_path(item['path'],e))['sha256']==item['sha256']
for name in ['native','worker','controller','driver','source_freeze']:assert pin(p[name]['path'])['sha256']==p[name]['sha256']
assert o.source_receipt(D/'source')==read(p['source_freeze']['path'])['source']
assert p['inputs']['reader_source']['sha256']=='1360653f2b3226bc578d1dd3e68f3598a0e762c9ab8d3fb345d2dadf46d637c7'
built=read(p['inputs']['build_result']['path']);captured=read(p['inputs']['capture_result']['path'])
assert built['native']==p['native']==captured['native'] and built['baseline_relinked_sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
assert captured['exact_failure_reproduced'] and captured['capture']['sha256']==p['inputs']['capture']['sha256']=='b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2'
assert r['compiler_command']==w.compile_command(built,Path(p['inputs']['reader_source']['path']),Path(r['reader']['path']))
assert pin(o.resolved_host_path(r['compiler_command'][0],e))['sha256']==e['runtime_artifacts']['cxx_compiler']['sha256']
assert r['compiler_version']==built['compiler_version']
assert r['reader_libraries']==built['reader_libraries']
for lib in r['reader_libraries']:assert pin(o.resolved_host_path(lib['path'],e))['sha256']==lib['sha256']
for item in [r['reader'],r['trace'],r['stderr']]:assert pin(item['path'])['sha256']==item['sha256']
trace=[json.loads(line)for line in Path(r['trace']['path']).read_text().splitlines()];old=[json.loads(line)for line in Path(captured['standalone']['trace']['path']).read_text().splitlines()]
base=[q for q in trace if q['kind']!='quad_residual'];quad=[q for q in trace if q['kind']=='quad_residual']
assert len(trace)==r['record_count']==200 and len(base)==198 and base==old
assert [q['iteration']for q in quad]==[6,120] and all(q['binary_digits']==113 for q in quad)
assert all(q['relative_residual_native_velocity_conversion']>2e-12 for q in quad)
assert trace[0]==r['input'] and trace[-1]==r['terminal']==captured['standalone']['terminal']
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==j['admission']['boot_id']==e['host']['boot_id']
absence=[]
for q in [j['admission']['driver_identity'],*j['cleanup']['identities']]:
 pid,start=q['pid'],q['start_ticks']
 try:
  now=o.proc(pid);assert now['start_ticks']!=start or now['state']=='Z';absence.append(dict(pid=pid,start_ticks=start,non_live=True,current_identity=now))
 except(FileNotFoundError,ProcessLookupError):absence.append(dict(pid=pid,start_ticks=start,non_live=True,absent=True))
print(json.dumps(dict(schema='orbit-poc-captured-tangent01-terminal-independent-readback-v1',passed=True,observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),plan=pin(C/'plan.json'),execution=pin(C/'execution.json'),pipeline=pin(C/'pipeline.json'),result=pin(O/'result.json'),reader=r['reader'],source=r['inputs']['reader_source'],capture=r['inputs']['capture'],trace=pin(r['trace']['path']),stderr=pin(r['stderr']['path']),eight_inputs_verified=r['inputs'],source_files_verified=384,compiler_command=r['compiler_command'],compiler_version=r['compiler_version'],reader_libraries=r['reader_libraries'],unchanged_baseline_trace_rows=len(base),quad_records=quad,terminal=r['terminal'],owned_identities_non_live=absence,finished_at=j['finished_at'],scope='Same failed double iterates and 198 baseline records preserved. Added 113-bit residuals at iterations 6 and 120 remain above the unchanged threshold. No numerical correction, convergence, covariance or release claim.',groops_propagations=0,fit_attempts=0),indent=2))
