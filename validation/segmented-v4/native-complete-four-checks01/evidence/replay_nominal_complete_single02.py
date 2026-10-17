#!/usr/bin/env python3
"""Single-propagation replay of a preserved native tangent failure; no fits."""
from pathlib import Path
from copy import deepcopy
import argparse,hashlib,json,re,xml.etree.ElementTree as ET
SCHEMA='orbit-poc-nominal-complete-single-replay-plan-v1'
INPUTS={'template','initial_orbit','initial_text','initial_state','bootstrap','initialization','request','attitude','satellite_model','eop','ephemerides','gravityfield','original_log','build_result','build_audit','supplemental_receipt'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(pin):
 p=Path(pin['path'])
 if set(pin)!={'path','sha256'} or not p.is_absolute() or '..' in p.parts or sha(p)!=pin['sha256']:raise ValueError('Pinned input changed')
 return p
def tree_for(template,folder):
 tree=deepcopy(template);programs=list(tree.findall('program'))
 if len(programs)!=3 or [list(p)[0].tag for p in programs]!=['PreprocessingVariationalEquation','OrbitPocEvaluateVariational','FileConvert']:raise ValueError('Exact three-program replay required')
 prop,ev,conv=[list(p)[0] for p in programs]
 if len(prop.findall('orbitPocDerivativeProfile'))!=1 or prop.findtext('orbitPocDerivativeProfile')!='synthetic_complete_v1' or prop.find('orbitPocDerivativeDiagnostics') is not None:raise ValueError('Preserved explicit synthetic profile required')
 for node,key in [(prop,'inputfileOrbit'),(ev,'inputfileInitialState')]:
  if node.find(key) is None or not node.findtext(key):raise ValueError('Original input path missing')
 changes=((prop,'outputfileVariational',folder/'variational.dat'),(ev,'inputfileVariational',folder/'variational.dat'),(ev,'outputfileOrbit',folder/'nominal.dat'),(conv,'inputfile',folder/'nominal.dat'),(conv,'outputfile',folder/'nominal.txt'))
 for node,key,value in changes:
  if node.find(key) is None:raise ValueError('Missing original path field '+key)
  node.find(key).text=str(value)
 return tree
def validate_plan(p):
 if set(p)!={'schema','execution','driver','worker','controller','native','source_freeze','inputs','output','global_lock'} or p['schema']!=SCHEMA:raise ValueError('Unknown diagnostic plan')
 if set(p['inputs'])!=INPUTS:raise ValueError('Exact diagnostic input inventory required')
 for key in ('output','global_lock'):
  if not Path(p[key]).is_absolute() or '..' in Path(p[key]).parts:raise ValueError('Canonical absolute paths required')
def failure_signature(text):
 lines=[re.sub(r'\x1b\[[0-9;]*m','',line) for line in text.splitlines() if 'six-state tangent did not meet its true residual tolerance:' in line]
 if len(lines)!=1:raise ValueError('Expected one original tangent failure signature')
 return lines[0]
def main(argv=None):
 a=argparse.ArgumentParser();a.add_argument('--plan',type=Path,required=True);a.add_argument('--sha256',required=True);q=a.parse_args(argv)
 if sha(q.plan)!=q.sha256:raise ValueError('Plan changed')
 p=json.loads(q.plan.read_text());validate_plan(p)
 import numpy as np
 from orbit_poc.comparison import backend
 from orbit_poc.comparison.protocol import write_json
 for item in p['inputs'].values():check(item)
 import complete_native_replay_attribution02 as attribution
 built,build_attribution=attribution.verify(p['inputs'],p['native'])
 supplemental=attribution.verify_supplemental(p['inputs']['supplemental_receipt'],built,p['inputs']['build_result'])
 binary=check(p['native']);template=ET.parse(check(p['inputs']['template'])).getroot();prop=template.find('./program/PreprocessingVariationalEquation');ev=template.find('./program/OrbitPocEvaluateVariational')
 if prop.findtext('inputfileOrbit')!=p['inputs']['initial_orbit']['path'] or ev.findtext('inputfileInitialState')!=p['inputs']['initial_state']['path']:raise ValueError('Original physical input paths differ')
 epochs,previous=backend._orbit(check(p['inputs']['initial_text']));recorded=json.loads(check(p['inputs']['initialization']).read_text());target=np.asarray(recorded['fixed_initial_state_si'])
 if recorded['maximum_iterations']!=10 or recorded['position_tolerance_m']!=2e-6 or recorded['velocity_tolerance_m_s']!=3e-9 or not np.array_equal(previous[0],target):raise ValueError('Original initialization criteria/state differ')
 signature=failure_signature(check(p['inputs']['original_log']).read_text());root=Path(p['output'])
 if root.exists():raise ValueError('Preserve previous replay output')
 root.mkdir();folder=root/'single-evaluation';folder.mkdir();xml=backend._save_xml(tree_for(template,folder),folder/'propagate.xml')
 result={'schema':'orbit-poc-fixed-state-tangent-replay-v1','status':'running','plan_sha256':q.sha256,'fixed_initial_state_si':target.tolist(),'state_epochs':len(epochs),'native':p['native'],'build_attribution':build_attribution,'analytical_supplemental':supplemental,'algorithm_delta':'Audited complete native build with wide tangent and typed interpolation integration. Original archived physical inputs, fixed target, profiles and solver/closure limits are retained; numerical equivalence remains under test.','xml_delta':'Only five output/intermediate path fields rebound; original inputs/profile/settings unchanged','native_evaluations':0,'fit_attempts':0,'release_evidence':False,'original_failure_signature':signature,'initialization_criteria':{k:recorded[k] for k in ('maximum_iterations','position_tolerance_m','velocity_tolerance_m_s')}}
 write_json(root/'result.json',result)
 try:
  result['native_evaluations']=1
  try:
   result['execution']=backend.run_native(binary,xml,folder,'propagate',timeout=7200.);result['status']='native_completed'
  except backend.NativeExecutionError as error:
   result.update(status='native_failed',execution=error.execution,error=repr(error))
   text=(folder/'propagate.log').read_text()
   try:result['replay_failure_signature']=failure_signature(text);result['exact_failure_reproduced']=result['replay_failure_signature']==signature
   except ValueError:result['exact_failure_reproduced']=False
  if result['status']=='native_completed':
   newepochs,states=backend._orbit(folder/'nominal.txt')
   if not np.array_equal(epochs,newepochs):raise ValueError('Epoch support changed')
   result['initial_state_error_si']=(states[0]-target).tolist()
   if not np.array_equal(states[0],target):raise ValueError('Fixed initial state changed')
  for item in p['inputs'].values():check(item)
  check(p['native'])
 except BaseException as error:result.update(status='controller_failed',error=repr(error));raise
 finally:write_json(root/'result.json',result)
 return 0 if result['status']=='native_completed' else 1
if __name__=='__main__':raise SystemExit(main())
