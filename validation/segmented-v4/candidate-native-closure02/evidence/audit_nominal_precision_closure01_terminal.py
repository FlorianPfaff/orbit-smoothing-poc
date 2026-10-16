from pathlib import Path
import hashlib,json,datetime,importlib.util,xml.etree.ElementTree as ET
import numpy as np
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-precision-closure-01';C=D/'control';O=D/'run/replay'
def pin(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),sha256=h.hexdigest(),bytes=p.stat().st_size)
def read(p):return json.loads(Path(p).read_text())
p=read(C/'plan.json');e=read(C/'execution.json');j=read(C/'pipeline.json');r=read(O/'result.json')
assert pin(C/'plan.json')['sha256']==r['plan_sha256']=='0d3f2f5e9e6c788e39fdbad5bfc4394c6a77676ce6a91ac58a9c3a82544f092e'
assert pin(C/'execution.json')['sha256']==p['execution']['sha256']=='833cc9c5eb2c238c8c0afebae9d7dbbbec8573b1c894dc0d991cfb95b408f813'
assert pin(C/'pipeline.json')['sha256']=='492182d229e1115568bc1b71f697b8cd787b55495e66ff61a13858e7dacc3f1a'
assert pin(O/'result.json')['sha256']=='6faab6b0c6fb854875238c51f3dcc37e8b6fd3728e098021e36412953d2de0d1'
assert r['status']=='closed' and r['converged'] and r['fit_attempts']==0 and r['native_evaluations']==4 and r['release_evidence']is False
assert j['status']=='passed_diagnostic'and j['returncode']==0 and j['interrupted_or_timeout']is False and j['final_cleanup']['verified']and not j['final_cleanup']['errors']
spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
spec=importlib.util.spec_from_file_location('worker',p['worker']['path']);w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
for item in p['inputs'].values():assert pin(o.resolved_host_path(item['path'],e))['sha256']==item['sha256']
for name in ['native','worker','controller','driver','source_freeze']:assert pin(p[name]['path'])['sha256']==p[name]['sha256']
assert o.source_receipt(D/'source')==read(p['source_freeze']['path'])['source']
built=read(p['inputs']['build_result']['path']);assert built['native']==p['native']==r['native']and p['native']['sha256']=='eb41fabb2117fd81c9d018793ad8e067f6ae65e86d71dae8e6ef8fcca4771133'
old=read(B/'tangent-replay-01/control/plan.json');assert {k:v for k,v in p['inputs'].items()if k!='build_result'}==old['inputs']
assert r['initialization_criteria']==dict(maximum_iterations=10,position_tolerance_m=2e-6,velocity_tolerance_m_s=3e-9)
target=np.array(read(p['inputs']['initialization']['path'])['fixed_initial_state_si']);assert np.array_equal(target,r['fixed_initial_state_si'])
previous=np.loadtxt(p['inputs']['initial_text']['path'],skiprows=6);epochs=previous[:,0];previous=previous[:,1:7];assert len(previous)==51840==r['state_epochs']and np.array_equal(previous[0],target)
original=ET.parse(p['inputs']['template']['path']).getroot()
def canon(t):return(t.tag,sorted(t.attrib.items()),(t.text or '').strip(),[canon(q)for q in t])
reference=Path(p['inputs']['initial_orbit']['path']);rows=[]
assert len(r['iterations'])==4 and [q['closed']for q in r['iterations']]==[False,False,False,True]
for index,row in enumerate(r['iterations'],1):
 folder=O/f'iteration-{index:02d}';actual=ET.parse(folder/'propagate.xml').getroot();expected=w.tree_for(original,folder)
 if index>1:expected.find('./program/PreprocessingVariationalEquation/inputfileOrbit').text=str(reference)
 assert canon(actual)==canon(expected)
 execution=read(folder/'propagate.execution.json');assert execution==row['execution']and execution['native_binary_sha256']==p['native']['sha256']and execution['config_sha256']==pin(folder/'propagate.xml')['sha256']
 assert execution['returncode']==0 and execution['timed_out']is False and execution['blas_openmp_threads']==1 and execution['command']==[p['native']['path'],str(folder/'propagate.xml')]
 values=np.loadtxt(folder/'nominal.txt',skiprows=6);assert np.array_equal(values[:,0],epochs);states=values[:,1:7];assert np.array_equal(states[0],target)and row['initial_state_error_si']==[0.]*6
 delta=states-previous;dp=float(np.linalg.norm(delta[:,:3],axis=1).max());dv=float(np.linalg.norm(delta[:,3:],axis=1).max())
 assert dp==row['maximum_position_change_m']and dv==row['maximum_velocity_change_m_s']and row['closed']==(dp<2e-6 and dv<3e-9)
 rows.append(dict(iteration=index,maximum_position_change_m=dp,maximum_velocity_change_m_s=dv,fixed_initial_state_exact=True,epoch_support_exact=True,closed=row['closed'],artifacts=[pin(folder/n)for n in ['propagate.xml','propagate.execution.json','propagate.log','nominal.txt','nominal.dat','variational.dat']]))
 previous=states;reference=folder/'nominal.dat'
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==j['admission']['boot_id']==e['host']['boot_id']
ids={(q['pid'],q['start_ticks'])for q in[j['admission']['driver_identity'],*j['cleanup']['identities']]};absence=[]
for pid,start in sorted(ids):
 try:
  now=o.proc(pid);assert now['start_ticks']!=start or now['state']=='Z';absence.append(dict(pid=pid,start_ticks=start,non_live=True))
 except(FileNotFoundError,ProcessLookupError):absence.append(dict(pid=pid,start_ticks=start,non_live=True,absent=True))
assert not(D/'run/manifest.json').exists()and not(D/'run/attempts').exists()
print(json.dumps(dict(schema='orbit-poc-nominal-precision-closure01-terminal-independent-readback-v1',passed=True,observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),plan=pin(C/'plan.json'),execution=pin(C/'execution.json'),pipeline=pin(C/'pipeline.json'),result=pin(O/'result.json'),native=p['native'],original_inputs_verified=13,build_input_verified=p['inputs']['build_result'],source_files_verified=384,independently_recomputed_iterations=rows,owned_identities_non_live=absence,finished_at=j['finished_at'],scope='Exact original72h failed inputs close under separately versioned precision candidate in four native propagations at unchanged numerical closure criteria. This is a fixed-state diagnostic, not a prepared benchmark, fit, complete prescribed validation or release.',native_propagations=4,fit_attempts=0,release_ready=False),indent=2))
