#!/usr/bin/env python3
"""Single-propagation replay of a preserved native tangent failure; no fits."""
from pathlib import Path
from copy import deepcopy
import argparse,hashlib,json,re,subprocess,xml.etree.ElementTree as ET,shutil,sys
SCHEMA='orbit-poc-nominal-tangent-current-capture-plan-v1'
INPUTS={'template','initial_orbit','initial_text','initial_state','bootstrap','initialization','request','attitude','satellite_model','eop','ephemerides','gravityfield','original_log','reader','build_result','fixture_manifest','baseline_plan','baseline_replay'}
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
def validate_current_baseline(p,build,recorded):
 plan_path=check(p['inputs']['baseline_plan']);plan=json.loads(plan_path.read_text());baseline=json.loads(check(p['inputs']['baseline_replay']).read_text())
 if baseline.get('status')!='native_failed' or baseline.get('plan_sha256')!=sha(plan_path) or plan.get('native')!=baseline.get('native'):raise ValueError('Current native failure attribution differs')
 if baseline.get('fixed_initial_state_si')!=recorded['fixed_initial_state_si'] or baseline.get('initialization_criteria')!={k:recorded[k]for k in('maximum_iterations','position_tolerance_m','velocity_tolerance_m_s')}:raise ValueError('Current failure changed original initial state or criteria')
 names={'template','initial_orbit','initial_text','initial_state','bootstrap','initialization','request','attitude','satellite_model','eop','ephemerides','gravityfield'}
 if any(plan['inputs'].get(k)!=p['inputs'][k]for k in names):raise ValueError('Current failure physical inputs differ')
 if build.get('status')!='built_diagnostic_only' or build.get('native')!=p['native'] or build.get('reader')!=p['inputs']['reader'] or build.get('original_native')!=baseline['native'] or build.get('baseline_relinked_sha256')!=baseline['native']['sha256']:raise ValueError('Capture build differs from current failed native')
 if failure_signature(check(p['inputs']['original_log']).read_text())!=baseline.get('replay_failure_signature'):raise ValueError('Current failure signature differs')
 return baseline
def run_reader_fixtures(pin,build_record,root):
 manifest=json.loads(check(pin).read_text())
 names={'replay.cpp','probe.cpp','test_quad.py','test_compensation.py','include/manifest.json','include/sixStateTangent.h','include/syntheticForceDerivatives.h','include/eventQuadrature.h','base_test_replay.py'}
 if set(manifest)!={'schema','files'} or manifest['schema']!='orbit-poc-tangent09-fixture-pins-v1' or set(manifest['files'])!=names:raise ValueError('Unexpected reader fixture inventory')
 for item in manifest['files'].values():check(item)
 if manifest['files']['replay.cpp']['path']!=build_record['reader_compile_command'][-3]:raise ValueError('Fixture reader source differs from built reader')
 work=root/'reader-fixtures';reader=work/'tangent72-diagnostic09';base=work/'tangent72-diagnostic01';reader.mkdir(parents=True);base.mkdir();(reader/'include').mkdir()
 for name,item in manifest['files'].items():shutil.copy2(item['path'],base/'test_replay.py' if name=='base_test_replay.py' else reader/name)
 shutil.copy2(build_record['reader']['path'],reader/'replay')
 command=[build_record['reader_compile_command'][0],'-O3','-DNDEBUG','-std=gnu++17','-I'+str(reader/'include'),str(reader/'probe.cpp'),'-o',str(reader/'probe')]
 with(work/'probe-compile.log').open('xb')as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
 test_command=[sys.executable,'-m','pytest','-q','-p','no:cacheprovider',str(reader/'test_quad.py'),str(reader/'test_compensation.py'),'--junitxml='+str(work/'tests.xml')]
 with(work/'tests.log').open('xb')as log:subprocess.run(test_command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
 suites=list(ET.parse(work/'tests.xml').getroot().iter('testsuite'))
 if len(suites)!=1 or any(int(suites[0].get(k,'0'))!=v for k,v in [('tests',3),('errors',0),('failures',0),('skipped',0)]):raise ValueError('Reader fixture test inventory differs')
 for item in manifest['files'].values():check(item)
 return {'status':'passed','compile_command':command,'test_command':test_command,'junit':{'path':str(work/'tests.xml'),'sha256':sha(work/'tests.xml')},'tests':3,'nested_original_reader_checks':8,'fit_attempts':0}
def main(argv=None):
 a=argparse.ArgumentParser();a.add_argument('--plan',type=Path,required=True);a.add_argument('--sha256',required=True);q=a.parse_args(argv)
 if sha(q.plan)!=q.sha256:raise ValueError('Plan changed')
 p=json.loads(q.plan.read_text());validate_plan(p)
 import numpy as np
 from orbit_poc.comparison import backend
 from orbit_poc.comparison.protocol import write_json
 for item in p['inputs'].values():check(item)
 binary=check(p['native']);template=ET.parse(check(p['inputs']['template'])).getroot();prop=template.find('./program/PreprocessingVariationalEquation');ev=template.find('./program/OrbitPocEvaluateVariational')
 if prop.findtext('inputfileOrbit')!=p['inputs']['initial_orbit']['path'] or ev.findtext('inputfileInitialState')!=p['inputs']['initial_state']['path']:raise ValueError('Original physical input paths differ')
 epochs,previous=backend._orbit(check(p['inputs']['initial_text']));recorded=json.loads(check(p['inputs']['initialization']).read_text());target=np.asarray(recorded['fixed_initial_state_si'])
 if recorded['maximum_iterations']!=10 or recorded['position_tolerance_m']!=2e-6 or recorded['velocity_tolerance_m_s']!=3e-9 or not np.array_equal(previous[0],target):raise ValueError('Original initialization criteria/state differ')
 build_record=json.loads(check(p['inputs']['build_result']).read_text());reader=check(p['inputs']['reader'])
 baseline=validate_current_baseline(p,build_record,recorded)
 signature=failure_signature(check(p['inputs']['original_log']).read_text());root=Path(p['output'])
 if root.exists():raise ValueError('Preserve previous replay output')
 root.mkdir();folder=root/'single-evaluation';folder.mkdir();xml=backend._save_xml(tree_for(template,folder),folder/'propagate.xml')
 result={'schema':'orbit-poc-fixed-state-tangent-capture-v1','status':'running','plan_sha256':q.sha256,'fixed_initial_state_si':target.tolist(),'state_epochs':len(epochs),'native':p['native'],'algorithm_delta':None,'current_baseline_replay':p['inputs']['baseline_replay'],'historical_initialization_native_sha256':recorded['native_binary_sha256'],'telemetry_delta':'Capture-only insertion before unchanged native solver; separately instrumented standalone reader','xml_delta':'Only five output/intermediate path fields rebound; original inputs/profile/settings unchanged','native_evaluations':0,'fit_attempts':0,'release_evidence':False,'original_failure_signature':signature,'initialization_criteria':{k:recorded[k] for k in ('maximum_iterations','position_tolerance_m','velocity_tolerance_m_s')}}
 write_json(root/'result.json',result)
 try:
  result['fixture_preflight']=run_reader_fixtures(p['inputs']['fixture_manifest'],build_record,root);write_json(root/'result.json',result)
  result['native_evaluations']=1
  try:
   result['execution']=backend.run_native(binary,xml,folder,'propagate',timeout=7200.,environment_overrides={'ORBIT_POC_TANGENT_CAPTURE':str(root/'captured-system.bin')});result['status']='native_completed'
  except backend.NativeExecutionError as error:
   result.update(status='native_failed',execution=error.execution,error=repr(error))
   text=(folder/'propagate.log').read_text()
   try:result['replay_failure_signature']=failure_signature(text);result['exact_failure_reproduced']=result['replay_failure_signature']==signature
   except ValueError:result['exact_failure_reproduced']=False
  captured=root/'captured-system.bin'
  if not captured.is_file():raise ValueError('Native operator capture was not produced')
  result['capture']={'path':str(captured),'bytes':captured.stat().st_size,'sha256':sha(captured)}
  trace=root/'standalone-trace.jsonl';errorlog=root/'standalone.stderr.log'
  with trace.open('xb')as out,errorlog.open('xb')as err:
   run=subprocess.run([str(reader),str(captured)],stdout=out,stderr=err,timeout=600,check=False)
  rows=[json.loads(line)for line in trace.read_text().splitlines()]
  if not rows or rows[0].get('kind')!='input' or rows[-1].get('kind')!='terminal':raise ValueError('Standalone trace lacks terminal attribution')
  result['standalone']={'returncode':run.returncode,'trace':{'path':str(trace),'sha256':sha(trace)},'stderr':{'path':str(errorlog),'sha256':sha(errorlog)},'record_count':len(rows),'input':rows[0],'terminal':rows[-1]}
  for item in p['inputs'].values():check(item)
  check(p['native'])
 except BaseException as error:result.update(status='controller_failed',error=repr(error));raise
 finally:write_json(root/'result.json',result)
 return 0 if result['status']=='native_completed' else 1
if __name__=='__main__':raise SystemExit(main())
