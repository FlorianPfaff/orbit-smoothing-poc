"""Read-only independent XML, saved-state and ownership audit; never executes native code."""
from pathlib import Path
from copy import deepcopy
import argparse,datetime,hashlib,importlib.util,json,xml.etree.ElementTree as ET
import numpy as np
ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--plan-sha256',required=True);ap.add_argument('--result-sha256',required=True);a=ap.parse_args()
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/a.root;C=D/'control';O=D/'run/replay'
assert a.root in ('tangent-complete-single-01','tangent-complete-single-02','tangent-complete-closure-01','tangent-complete-closure-02')
def pin(path):
 p=Path(path);h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return {'path':str(p),'sha256':h.hexdigest(),'bytes':p.stat().st_size}
def read(path):return json.loads(Path(path).read_text())
def canon(t):return(t.tag,sorted(t.attrib.items()),(t.text or '').strip(),[canon(q)for q in t])
p=read(C/'plan.json');e=read(C/'execution.json');j=read(C/'pipeline.json');r=read(O/'result.json');launch=read(C/('native-single-launch.json'if 'single'in a.root else'native-closure-launch.json'))
assert pin(C/'plan.json')['sha256']==a.plan_sha256==r['plan_sha256'];assert pin(O/'result.json')['sha256']==a.result_sha256
assert pin(C/'execution.json')['sha256']==p['execution']['sha256']==launch['execution_sha256']
assert p['native']==r['native']and r['native']['sha256']=='643a1b6d523a363eae88902f2a2d4807452ea3edbd504bceaad23a94d65fb2f6'
assert r['build_attribution']['build_result']==p['inputs']['build_result']and r['build_attribution']['build_audit']==p['inputs']['build_audit']
assert r['analytical_supplemental']['receipt']==p['inputs']['supplemental_receipt']and r['analytical_supplemental']['executed_in_this_replay']is False
assert r['fit_attempts']==0 and r['release_evidence']is False
spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);owned=importlib.util.module_from_spec(spec);spec.loader.exec_module(owned)
for key in('worker','controller','driver'):assert pin(p[key]['path'])['sha256']==p[key]['sha256']
for item in p['inputs'].values():assert pin(owned.resolved_host_path(item['path'],e))['sha256']==item['sha256']
initial=read(p['inputs']['initialization']['path']);criteria={k:initial[k]for k in('maximum_iterations','position_tolerance_m','velocity_tolerance_m_s')}
assert criteria==r['initialization_criteria']=={'maximum_iterations':10,'position_tolerance_m':2e-6,'velocity_tolerance_m_s':3e-9}
target=np.asarray(initial['fixed_initial_state_si']);assert np.array_equal(target,r['fixed_initial_state_si'])
old=np.loadtxt(p['inputs']['initial_text']['path'],skiprows=6);epochs=old[:,0];previous=old[:,1:7];assert len(old)==51840==r['state_epochs']and np.array_equal(previous[0],target)
original=ET.parse(p['inputs']['template']['path']).getroot();assert original.findtext('./program/PreprocessingVariationalEquation/orbitPocDerivativeProfile')=='synthetic_complete_v1'
assert original.findtext('./program/PreprocessingVariationalEquation/inputfileOrbit')==p['inputs']['initial_orbit']['path']
assert original.findtext('./program/OrbitPocEvaluateVariational/inputfileInitialState')==p['inputs']['initial_state']['path']
assert j['final_cleanup']['verified']and not j['final_cleanup']['errors']and not j['interrupted_or_timeout']
single='single' in a.root;rows=[{'execution':r['execution']}]if single else r['iterations'];assert r['native_evaluations']==len(rows)and 1<=len(rows)<= (1 if single else 10)
reference=Path(p['inputs']['initial_orbit']['path']);results=[]
for i,row in enumerate(rows,1):
 folder=O/('single-evaluation'if single else f'iteration-{i:02d}');actual=ET.parse(folder/'propagate.xml').getroot();expected=deepcopy(original)
 for path,value in(('./program/PreprocessingVariationalEquation/outputfileVariational',folder/'variational.dat'),('./program/OrbitPocEvaluateVariational/inputfileVariational',folder/'variational.dat'),('./program/OrbitPocEvaluateVariational/outputfileOrbit',folder/'nominal.dat'),('./program/FileConvert/inputfile',folder/'nominal.dat'),('./program/FileConvert/outputfile',folder/'nominal.txt')):expected.find(path).text=str(value)
 if i>1:expected.find('./program/PreprocessingVariationalEquation/inputfileOrbit').text=str(reference)
 assert canon(actual)==canon(expected),'XML physical/settings delta'
 execution=read(folder/'propagate.execution.json');assert execution==row['execution']and execution['native_binary_sha256']==p['native']['sha256']and execution['config_sha256']==pin(folder/'propagate.xml')['sha256']
 assert execution['blas_openmp_threads']==1 and execution['command']==[p['native']['path'],str(folder/'propagate.xml')]and not execution['timed_out']
 result={'iteration':i,'execution':execution,'xml_output_only':True,'artifacts':[pin(folder/n)for n in('propagate.xml','propagate.execution.json','propagate.log')]}
 if execution['returncode']==0:
  values=np.loadtxt(folder/'nominal.txt',skiprows=6);states=values[:,1:7];assert np.array_equal(values[:,0],epochs)and np.array_equal(states[0],target)
  assert (r if single else row)['initial_state_error_si']==[0.]*6
  result.update(fixed_initial_state_exact=True,epoch_support_exact=True,state_epochs=len(values),artifacts=result['artifacts']+[pin(folder/n)for n in('nominal.txt','nominal.dat','variational.dat')])
  if not single:
   delta=states-previous;dp=float(np.linalg.norm(delta[:,:3],axis=1).max());dv=float(np.linalg.norm(delta[:,3:],axis=1).max());closed=dp<2e-6 and dv<3e-9
   assert dp==row['maximum_position_change_m']and dv==row['maximum_velocity_change_m_s']and closed==row['closed']
   result.update(maximum_position_change_m=dp,maximum_velocity_change_m_s=dv,closed=closed)
  previous=states;reference=folder/'nominal.dat'
 else:
  assert i==len(rows);result['native_failure_preserved']=True
 results.append(result)
if single:
 assert (r['status']=='native_completed')==(results[0]['execution']['returncode']==0)
else:
 assert r['converged']==(r['status']=='closed')==bool(results[-1].get('closed',False))
 assert not any(x.get('closed',False)for x in results[:-1])
assert (j['status']=='passed_diagnostic')==(r['status']in('native_completed','closed'))
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==j['admission']['boot_id']==e['host']['boot_id']==launch['driver_process']['boot_id']
ids={(q['pid'],q['start_ticks'])for cmd in j['final_cleanup']['commands']for q in cmd['identities']};ids.add((launch['driver_process']['pid'],launch['driver_process']['start_ticks']));absence=[]
for pid,tick in sorted(ids):
 try:
  now=owned.proc(pid);live=now['start_ticks']==tick and now['state']not in('Z','X');row={'pid':pid,'start_ticks':tick,'live':live,'observed_state':now['state']}
 except(FileNotFoundError,ProcessLookupError):row={'pid':pid,'start_ticks':tick,'live':False,'absent':True}
 assert not row['live'];absence.append(row)
assert not(D/'run/manifest.json').exists()and not(D/'run/attempts').exists()
print(json.dumps({'schema':'orbit-poc-complete-native-terminal-independent-readback-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'root':str(D),'plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'pipeline':pin(C/'pipeline.json'),'result':pin(O/'result.json'),'native':p['native'],'status':r['status'],'physical_inputs_verified':13,'explicit_build_and_supplemental_inputs_verified':3,'fixed_initial_state_si':target.tolist(),'initialization_criteria':criteria,'iterations':results,'owned_identities':absence,'native_propagations':len(rows),'fit_attempts':0,'release_ready':False,'scope':'Read-only independent exact XML/input attribution and saved trajectory checks. Native failure, if present, remains failed. No new propagation, covariance, full-suite or release certification.'},indent=2))
