#!/usr/bin/env python3
"""Diagnostic-only replay of an archived fixed-state nominal closure."""
from pathlib import Path
from copy import deepcopy
import argparse,hashlib,json,xml.etree.ElementTree as ET

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(pin):
 p=Path(pin['path'])
 if set(pin)!={'path','sha256'} or not p.is_absolute() or sha(p)!=pin['sha256']:raise ValueError('Pinned input changed')
 return p

def tree_for(template,reference,initial,folder):
 tree=deepcopy(template);programs=list(tree.findall('program'))
 if len(programs)!=3 or [list(p)[0].tag for p in programs]!=['PreprocessingVariationalEquation','OrbitPocEvaluateVariational','FileConvert']:raise ValueError('Exact three-program replay required')
 prop,ev,conv=[list(p)[0] for p in programs]
 if prop.find('orbitPocDerivativeProfile') is not None or prop.find('orbitPocDerivativeDiagnostics') is not None:raise ValueError('Original profile must be absent')
 ET.SubElement(prop,'orbitPocDerivativeProfile').text='synthetic_complete_v1'
 ET.SubElement(prop,'orbitPocDerivativeDiagnostics').text=str(folder/'derivatives.json')
 changes=((prop,'inputfileOrbit',reference),(prop,'outputfileVariational',folder/'variational.dat'),(ev,'inputfileVariational',folder/'variational.dat'),(ev,'outputfileOrbit',folder/'nominal.dat'),(ev,'inputfileInitialState',initial),(conv,'inputfile',folder/'nominal.dat'),(conv,'outputfile',folder/'nominal.txt'))
 for node,key,value in changes:
  child=node.find(key)
  if child is None:raise ValueError('Missing original path field '+key)
  child.text=str(value)
 return tree

def validate_plan(p):
 if set(p)!={'schema','execution','driver','worker','controller','native','source_freeze','inputs','output','global_lock'} or p['schema']!='orbit-poc-nominal-profile-diagnostic-plan-v1':raise ValueError('Unknown diagnostic plan')
 if set(p['inputs'])!={'template','initial_orbit','initial_text','initial_state','bootstrap','initialization','request','attitude','satellite_model','eop','ephemerides','gravityfield'}:raise ValueError('Exact diagnostic input inventory required')
 for key in ('output','global_lock'):
  if not Path(p[key]).is_absolute() or '..' in Path(p[key]).parts:raise ValueError('Canonical absolute paths required')

def main(argv=None):
 a=argparse.ArgumentParser();a.add_argument('--plan',type=Path,required=True);a.add_argument('--sha256',required=True);q=a.parse_args(argv)
 if sha(q.plan)!=q.sha256:raise ValueError('Plan changed')
 p=json.loads(q.plan.read_text());validate_plan(p);import numpy as np
 from orbit_poc.comparison import backend
 from orbit_poc.comparison.protocol import write_json
 for pin in p['inputs'].values():check(pin)
 binary=check(p['native']);root=Path(p['output']);
 if root.exists():raise ValueError('Preserve previous replay output')
 root.mkdir();template=ET.parse(check(p['inputs']['template'])).getroot();reference=check(p['inputs']['initial_orbit']);initial=check(p['inputs']['initial_state']);epochs,previous=backend._orbit(check(p['inputs']['initial_text']))
 recorded=json.loads(check(p['inputs']['initialization']).read_text());target=np.array(recorded['fixed_initial_state_si'])
 if recorded['maximum_iterations']!=10 or recorded['position_tolerance_m']!=2e-6 or recorded['velocity_tolerance_m_s']!=3e-9 or not np.array_equal(previous[0],target):raise ValueError('Original initialization criteria/state differ')
 result={'schema':'orbit-poc-fixed-state-profile-diagnostic-v1','status':'running','plan_sha256':q.sha256,'fixed_initial_state_si':target.tolist(),'state_epochs':len(epochs),'iterations':[],'native':p['native'],'algorithm_delta':{'orbitPocDerivativeProfile':['absent(default legacy_v3)','synthetic_complete_v1']},'telemetry_delta':'orbitPocDerivativeDiagnostics per iteration','maximum_iterations':10,'position_tolerance_m':2e-6,'velocity_tolerance_m_s':3e-9,'fit_attempts':0,'release_evidence':False}
 write_json(root/'result.json',result)
 try:
  for i in range(1,11):
   folder=root/f'iteration-{i:02d}';folder.mkdir();xml=backend._save_xml(tree_for(template,reference,initial,folder),folder/'propagate.xml')
   execution=backend.run_native(binary,xml,folder,'propagate',timeout=600.)
   newepochs,states=backend._orbit(folder/'nominal.txt')
   if not np.array_equal(epochs,newepochs):raise ValueError('Epoch support changed')
   delta=states-previous;dp=float(np.max(np.linalg.norm(delta[:,:3],axis=1)));dv=float(np.max(np.linalg.norm(delta[:,3:],axis=1)));closed=dp<2e-6 and dv<3e-9
   derivative=json.loads((folder/'derivatives.json').read_text())
   result['iterations'].append({'iteration':i,'maximum_position_change_m':dp,'maximum_velocity_change_m_s':dv,'maximum_initial_state_error_si':(states[0]-target).tolist(),'closed':closed,'execution':execution,'derivatives':derivative})
   write_json(root/'result.json',result)
   if closed:result.update(status='closed',converged=True);break
   reference,previous=folder/'nominal.dat',states
  else:result.update(status='not_closed',converged=False)
  for pin in p['inputs'].values():check(pin)
  check(p['native'])
 except BaseException as e:
  result.update(status='failed',converged=False,error=repr(e));raise
 finally:write_json(root/'result.json',result)
 return 0 if result['status']=='closed' else 1
if __name__=='__main__':raise SystemExit(main())
