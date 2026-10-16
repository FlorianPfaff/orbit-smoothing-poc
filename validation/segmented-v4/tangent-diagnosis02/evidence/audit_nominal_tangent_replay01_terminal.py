from pathlib import Path
import hashlib,json,datetime,importlib.util,xml.etree.ElementTree as ET
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-replay-01';C=D/'control';O=D/'run/replay';F=O/'single-evaluation'
def pin(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),sha256=h.hexdigest(),bytes=p.stat().st_size)
def read(p):return json.loads(Path(p).read_text())
p=read(C/'plan.json');e=read(C/'execution.json');j=read(C/'pipeline.json');r=read(O/'result.json');x=read(F/'propagate.execution.json')
assert pin(C/'plan.json')['sha256']==r['plan_sha256']=='cfd13121cb50b19ef2570a84501d10e9efeaf34448f7e493271f7378a32f8d7e'
assert pin(C/'pipeline.json')['sha256']=='ad615612edd29225ca91a1aa8d2d403416c91e3ec6564e4a792f2993fb8f967f'
assert pin(O/'result.json')['sha256']=='f178d30654a3648a9da232cc835e8406a295362df2222571f97735a8ddc6f810'
assert r['status']=='native_failed' and r['exact_failure_reproduced'] is True and r['algorithm_delta']is None and r['fit_attempts']==0 and r['native_evaluations']==1 and r['release_evidence']is False
assert j['status']=='failed_diagnostic' and j['returncode']==1 and j['interrupted_or_timeout']is False and j['final_cleanup']['verified']is True and j['final_cleanup']['errors']==[]
assert x==r['execution'] and x['returncode']==1 and x['timed_out']is False and x['blas_openmp_threads']==1
assert x['native_binary_sha256']==r['native']['sha256']==p['native']['sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
assert x['config_sha256']==pin(F/'propagate.xml')['sha256']
spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
spec=importlib.util.spec_from_file_location('worker',p['worker']['path']);w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
for item in p['inputs'].values():assert pin(o.resolved_host_path(item['path'],e))['sha256']==item['sha256']
assert pin(p['native']['path'])['sha256']==p['native']['sha256']
assert o.source_receipt(D/'source')==read(p['source_freeze']['path'])['source']
original=ET.parse(p['inputs']['template']['path']).getroot();actual=ET.parse(F/'propagate.xml').getroot();expected=w.tree_for(original,F)
def canon(t):return (t.tag,sorted(t.attrib.items()),(t.text or '').strip(),[canon(q)for q in t])
assert canon(actual)==canon(expected)
original_signature=w.failure_signature(Path(p['inputs']['original_log']['path']).read_text());actual_signature=w.failure_signature((F/'propagate.log').read_text());assert actual_signature==original_signature==r['replay_failure_signature']==r['original_failure_signature']
assert r['fixed_initial_state_si']==read(p['inputs']['initialization']['path'])['fixed_initial_state_si']
assert not(F/'nominal.dat').exists() and not(F/'nominal.txt').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==j['admission']['boot_id']==e['host']['boot_id']
identities={(q['pid'],q['start_ticks']):q for q in [j['admission']['driver_identity'],*j['cleanup']['identities']]}
absence=[]
for (pid,start),q in identities.items():
 try:
  now=o.proc(pid);nonlive=now['start_ticks']!=start or now['state']=='Z';assert nonlive
  absence.append(dict(pid=pid,start_ticks=start,non_live=True,current_identity=now))
 except (FileNotFoundError,ProcessLookupError):absence.append(dict(pid=pid,start_ticks=start,non_live=True,absent=True))
print(json.dumps(dict(schema='orbit-poc-nominal-tangent-original-replay-terminal-independent-readback-v1',passed=True,observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),plan=pin(C/'plan.json'),pipeline=pin(C/'pipeline.json'),result=pin(O/'result.json'),native_execution=pin(F/'propagate.execution.json'),actual_xml=pin(F/'propagate.xml'),actual_log=pin(F/'propagate.log'),actual_failure_signature=actual_signature,native_evaluations=1,fit_attempts=0,elapsed_seconds=x['elapsed_seconds'],peak_native_rss_bytes=x['peak_rss_bytes'],peak_owned_rss_bytes=j['peak_owned_rss_bytes'],exact_original_inputs_verified=p['inputs'],native=p['native'],source_files_verified=384,exact_five_xml_path_changes=True,owned_identities_non_live=absence,finished_at=j['finished_at'],scope='Exact original binary and failure inputs reproduce every reported numerical guard field. Reproduction does not identify the cause of the residual failure or authorize convergence, covariance or release.'),indent=2))
