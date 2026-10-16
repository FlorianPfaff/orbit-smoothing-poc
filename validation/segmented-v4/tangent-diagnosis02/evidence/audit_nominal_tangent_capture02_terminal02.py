from pathlib import Path
import hashlib,json,datetime,importlib.util,xml.etree.ElementTree as ET,struct,math
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-telemetry-02';C=D/'control';O=D/'run/replay';F=O/'single-evaluation'
def pin(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),sha256=h.hexdigest(),bytes=p.stat().st_size)
def read(p):return json.loads(Path(p).read_text())
p=read(C/'plan.json');e=read(C/'execution.json');j=read(C/'pipeline.json');r=read(O/'result.json');x=read(F/'propagate.execution.json')
assert pin(C/'plan.json')['sha256']==r['plan_sha256']=='e43e2f0fe1f078a5969b7a89d852436f8baec6db75e62fa987e456e39ddaf1e1'
assert pin(C/'execution.json')['sha256']==p['execution']['sha256']=='953bc5d15901e3af946abcc0ed912e2ef3461c182e3eb90d14c42f4afc2ed239'
assert pin(C/'pipeline.json')['sha256']=='f50b2c8407c3a69e8125d288ae5ed639dec48399dc5fbb63679cc49bcb78728f'
assert pin(O/'result.json')['sha256']=='f5a87f7ce1a038e1d1af08f6d432791a53397a31decaec2ce74c366eb33d90d8'
assert r['status']=='native_failed' and r['exact_failure_reproduced'] is True and r['algorithm_delta']is None and r['fit_attempts']==0 and r['native_evaluations']==1 and r['release_evidence']is False
assert j['status']=='failed_diagnostic' and j['returncode']==1 and j['interrupted_or_timeout']is False and j['final_cleanup']['verified']is True and j['final_cleanup']['errors']==[]
assert x==r['execution'] and x['returncode']==1 and x['timed_out']is False and x['blas_openmp_threads']==1
assert x['native_binary_sha256']==r['native']['sha256']==p['native']['sha256']=='e444cec3fc972fac1800ab0d41e223dfc9eaee761c8d85b34588cec1702b897c'
assert x['config_sha256']==pin(F/'propagate.xml')['sha256']
spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
spec=importlib.util.spec_from_file_location('worker',p['worker']['path']);w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
for item in p['inputs'].values():assert pin(o.resolved_host_path(item['path'],e))['sha256']==item['sha256']
for name in ['native','worker','controller','driver','source_freeze']:assert pin(p[name]['path'])['sha256']==p[name]['sha256']
assert o.source_receipt(D/'source')==read(p['source_freeze']['path'])['source']
built=read(p['inputs']['build_result']['path']);assert built['native']==p['native'] and built['reader']==p['inputs']['reader'] and built['baseline_relinked_sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
original=ET.parse(p['inputs']['template']['path']).getroot();actual=ET.parse(F/'propagate.xml').getroot();expected=w.tree_for(original,F)
def canon(t):return (t.tag,sorted(t.attrib.items()),(t.text or '').strip(),[canon(q)for q in t])
assert canon(actual)==canon(expected)
original_signature=w.failure_signature(Path(p['inputs']['original_log']['path']).read_text());actual_signature=w.failure_signature((F/'propagate.log').read_text());assert actual_signature==original_signature==r['replay_failure_signature']==r['original_failure_signature']
assert r['fixed_initial_state_si']==read(p['inputs']['initialization']['path'])['fixed_initial_state_si']
assert not(F/'nominal.dat').exists() and not(F/'nominal.txt').exists()
for item in [r['capture'],r['standalone']['trace'],r['standalone']['stderr']]:assert pin(item['path'])['sha256']==item['sha256']
trace=[json.loads(line)for line in Path(r['standalone']['trace']['path']).read_text().splitlines()]
assert len(trace)==r['standalone']['record_count']==198 and trace[0]==r['standalone']['input'] and trace[-1]==r['standalone']['terminal']
assert trace[0]==dict(kind='input',epochs=51840,dt=5,duration=259195,tolerance=2e-12,maximum_iterations=120,restart=20,extended_digits=64)
assert trace[-1]==dict(kind='terminal',status='failed',iterations=120,relative_residual=1.503709478355439e-11)
assert r['standalone']['returncode']==1
true=[q for q in trace if q['kind']=='true_residual'];proj=[q for q in trace if q['kind']=='projected_residual']
assert len(proj)==120 and [q['iteration']for q in proj]==list(range(1,121))
assert true[-1]['final'] and true[-1]['iteration']==120 and true[-1]['native_relative_residual']==trace[-1]['relative_residual']
assert all(math.isfinite(v)for q in trace for v in q.values()if isinstance(v,(float,int)))
raw=Path(r['capture']['path']).read_bytes();assert raw[:16]==b'OPCTANGENT001\n\0\0'
schema,n,intervals,terms,rhs=struct.unpack_from('<5Q',raw,16);dt,T=struct.unpack_from('<2d',raw,56)
assert (schema,n,intervals,rhs,dt,T)==(1,51840,51839,311040,5.,259195.)
pos=72+2*n*18*8;observed_terms=0
for k in range(intervals):
 count,=struct.unpack_from('<Q',raw,pos);pos+=8;assert count<=100;observed_terms+=count
 for z in range(count):
  index,integral,moment=struct.unpack_from('<Qdd',raw,pos);pos+=24;assert index<n and math.isfinite(integral)and math.isfinite(moment)
assert observed_terms==terms and pos+rhs*8==len(raw)==r['capture']['bytes']==27786112
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==j['admission']['boot_id']==e['host']['boot_id']
# Preserved first telemetry attempt failed before native execution because reader mount was missing.
D1=B/'tangent-telemetry-01';e1=read(D1/'control/execution.json');p1=read(D1/'control/plan.json');j1=read(D1/'control/pipeline.json')
assert j1['status']=='failed_diagnostic' and j1['final_cleanup']['verified'] and j1['final_cleanup']['errors']==[]
assert not(D1/'run/replay').exists()
log1=Path(D1/'control/worker.log');assert log1.is_file()
s=log1.read_text();assert 'FileNotFoundError' in s and str(B/'tangent-capture-03/binaries/tangent-replay')in s
extra={'source':str(B/'tangent-capture-03'),'target':str(B/'tangent-capture-03')}
assert e['read_only_bindings']==e1['read_only_bindings']+[extra]
assert p['inputs']==p1['inputs'] and p['native']==p1['native']
identities={}
for job in [j,j1]:
 for q in [job['admission']['driver_identity'],*job['cleanup']['identities']]:identities[(q['pid'],q['start_ticks'])]=q
absence=[]
for (pid,start),q in identities.items():
 try:
  now=o.proc(pid);assert now['start_ticks']!=start or now['state']=='Z';absence.append(dict(pid=pid,start_ticks=start,non_live=True,current_identity=now))
 except(FileNotFoundError,ProcessLookupError):absence.append(dict(pid=pid,start_ticks=start,non_live=True,absent=True))
print(json.dumps(dict(schema='orbit-poc-nominal-tangent-capture02-terminal-independent-readback-v1',passed=True,observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),plan=pin(C/'plan.json'),execution=pin(C/'execution.json'),pipeline=pin(C/'pipeline.json'),result=pin(O/'result.json'),native_execution=pin(F/'propagate.execution.json'),actual_xml=pin(F/'propagate.xml'),actual_log=pin(F/'propagate.log'),actual_failure_signature=actual_signature,native_evaluations=1,fit_attempts=0,elapsed_seconds=x['elapsed_seconds'],peak_native_rss_bytes=x['peak_rss_bytes'],peak_owned_rss_bytes=j['peak_owned_rss_bytes'],exact_original_inputs_verified=p['inputs'],native=p['native'],source_files_verified=384,exact_five_xml_path_changes=True,capture=pin(r['capture']['path']),capture_dimensions=dict(schema=schema,epochs=n,intervals=intervals,terms=terms,rhs_count=rhs,dt=dt,duration=T),standalone_trace=pin(r['standalone']['trace']['path']),standalone_stderr=pin(r['standalone']['stderr']['path']),trace_records=len(trace),projected_records=len(proj),true_records=len(true),final_true_record=true[-1],terminal=trace[-1],preserved_attempt01=dict(pipeline=pin(D1/'control/pipeline.json'),log=pin(log1),failure='Missing read-only capture build namespace binding; no worker output or native execution',output_absent=True),owned_identities_non_live=absence,finished_at=j['finished_at'],scope='Exact capture binary and standalone reader reproduce the original native failure signature and terminal residual. No numerical correction, convergence, covariance or release claim. Extended residuals are diagnostics on the same double iterate.'),indent=2))
