#!/usr/bin/env python3
"""Independent, scoped audit of the completed validation04 gates; no execution."""
from pathlib import Path
import argparse,ast,datetime,gzip,hashlib,json,math,xml.etree.ElementTree as ET
R='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-04'
C=Path('/mnt/d/orbit-segmented-v4/control')
SOURCE=Path('/mnt/d/orbit-segmented-v4/source')
STAGES=['native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses']
NATIVE='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
SOLVER='2c8481050806ce9d4c89d4c605fd9036bed3cdfb97010efeb359213aa0dbc223'
FULL='1fe0f24166a7983a7c10eaf1712e4b5545f02c61bd38406fa9d07e70cd7d6a4e'
COMPARISON='68e17e5b5ebe6fe22a47b9c6213c89397cfb80e25cc5e033da2621fc0aa44474'
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(v):return sha(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def pin(p):
 p=Path(p);b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def need(ok,m):
 if not ok:raise AssertionError(m)
def close(a,b):return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-15)

def replay_check(x,directory,raw,pins,index,art):
 need(x['schema']=='orbit-poc-native-nuisance-validation-v1' and x['native_sha256']==NATIVE and x['native_unchanged'] and x['passed'] and x['returncode']==0 and x['timed_out'] is False,'replay execution identity')
 need(x['strict_nuisance_converged'] and not x['progress_only_floor_validated'],'strict replay status')
 p=x['profile'];need(p['nuisance_converged'] and not p['nuisance_floor_limited'] and p['nuisance_floor_audit']==[] and p['nuisance_objective_resolution']==0,'strict replay profile')
 need(p['fixed_weights'] and not p['dynamic_updates'] and p['threshold_m']==1e-8 and p['required_consecutive_small_updates']==2,'unchanged replay policy')
 history=p['history'];searches=x['searches'];need(len(history)==len(searches)==p['iterations'] and len(history)>=2,'replay full history')
 profile_path=directory+'/result/qr.profile.json';need(json.loads(raw[profile_path])==p,'raw replay profile equals reported profile');art.append(pins[profile_path])
 need(all(0<=a['maximum_update_m']<1e-8 for a in history[-2:]) and p['maximum_update_m']==history[-1]['maximum_update_m'],'last two strict undamped updates')
 need(x['zero_update_replay_exact'] and x['fixed_observations_and_weights_verified_every_trial'],'zero transaction and fixed support')
 for i,s in enumerate(searches):
  sp=directory+f'/result/qr.{i+1}.nuisance_line_search.json';need(sha(raw[sp])==s['sha256'],'raw native replay search hash');native_search=json.loads(raw[sp]);need(s=={'generation':i+1,'sha256':s['sha256'],**native_search},'raw replay search equality');art.append(pins[sp])
  z=s['zero_update_replay'];need(s['generation']==i+1 and z['status']==0 and z['actual_reduction']==0 and z['maximum_update_m']==0 and z['cost']==s['objective_before'],'zero replay exact')
 signatures={t.get('observation_signature') for s in searches for t in s['trials'] if t['status']==0};need(len(signatures)==1 and None not in signatures and '0' not in signatures and sum(t.get('ambiguity_half_integer_crossings',0) for s in searches for t in s['trials'] if t['status']==0)==x['ambiguity_half_integer_crossings_tested']>0,'all native trial support and ambiguity crossing checks')
 for s in searches[-2:]:need(s['stationary_without_update'] and not s['nuisance_floor_limited'] and 0<=s['undamped_maximum_update_m']<1e-8,'fresh strict final search')
 inputs_path=Path('/mnt/d/orbit-segmented-v4/deployment-inventory-04/output/validation-inputs.json');need(pin(inputs_path)['sha256']=='50d9d05d275d48f6039a9478397c5470e9391ca32e53ed67c7d6b32d2bd0edb4','original inventory bytes');inputs=json.loads(inputs_path.read_bytes())['input_artifacts'];role='old_nuisance_replay' if index==8 else 'candidate1_nuisance_replay';prefix='old' if index==8 else 'new';original=inputs[role]
 source=Path(original['path']).read_bytes();need(sha(source)==original['sha256']==x['source_profile_sha256'],'distinct original replay XML pin');executed_path=directory+'/result/profile.xml';executed=raw[executed_path];need(sha(executed)==x['replay_profile_sha256'],'executed replay XML pin');art.append(pins[executed_path]);trees=[ET.fromstring(b) for b in (source,executed)]
 physical={}
 for tag,key in [('inputfileVariational','variational'),('inputfileNumericsReferenceParameters','reference'),('inputfileLogDensity','density')]:
  expected=inputs[prefix+'_replay_'+key];vals=[[(e.text or '').strip() for e in tree.iter(tag)] for tree in trees];need(vals[0] and vals[0]==vals[1] and all(v==expected['path'] for v in vals[0]),'replay physical input path identity');physical[key]=expected
 need(x['build_manifest_sha256']=='767bcbeb57763d7ac75d2e385e949782f0c2e4d6b475904cbc1127e4c08ad058','same-byte build sidecar')
 return {'strict_nuisance_converged':True,'floor_limited':False,'iterations':len(history),'maximum_update_m':p['maximum_update_m'],'last_two_undamped_updates_m':[a['maximum_update_m'] for a in history[-2:]],'original_profile':original,'physical_input_pins':physical,'input_verification_scope':'Exact original14 inventory and XML identity; physical file bytes were independently verified in the pinned actual prelaunch audit and frozen public runtime/input verifier.','zero_update_replay_exact':True,'fixed_support_and_weights':True,'sidecar_resolved':True}

def linearization_check(x,raw,pins,art,index):
 import io
 import numpy as np
 from scipy.linalg import solve_triangular,qr,lstsq,svdvals
 def finite(v,limit):return isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<limit
 def load(p):
  need(p['path'] in raw,'missing linearization artifact '+p['path']);b=raw[p['path']];need(sha(b)==p['sha256'],'linearization artifact hash');art.append(pins[p['path']]);return b
 def npz(p):
  with np.load(io.BytesIO(load(p)),allow_pickle=False) as z:return {k:z[k] for k in z.files}
 def same(a,b,tol=5e-12):return abs(a-b)<=tol*max(1.,abs(a),abs(b))
 need(x['schema']=='orbit-poc-segmented-linearization-gate-v1' and x['passed'] and x['source_sha256']==COMPARISON and x['native']['sha256']==NATIVE and x['solver']['sha256']==SOLVER,'linearization source/runtime')
 expected_request='2189944cfb519b5ca0730e6e02ee9cb809145a0845f66846931a8fb199694dfd' if index==12 else '9de707ae51e5031a5b13f1d02ab5ec5a67e996195840de6c5c7e81457a74c9f5'
 need(x['original_request']['sha256']==expected_request,'exact original blind linearization request');original_bytes=Path(x['original_request']['path']).read_bytes();need(sha(original_bytes)==expected_request,'original blind request bytes');original=json.loads(original_bytes);derived=json.loads(load(x['request']));expected=json.loads(original_bytes);expected['preparation_source_hash']=expected['source_hash'];expected['source_hash']=COMPARISON;expected['backend']['groops_executable']=x['native']['path'];expected['backend']['segmented_solver']={'path':x['solver']['path'],'sha256':SOLVER};expected['expected_native_binary_sha256']=NATIVE;expected['segmented_profile']='segmented_1h';need(derived==expected,'blind request changes limited to execution identity');need(x['initial_state_input']['sha256']=='61b08f300902d38357b3ea6889711818a3ae590af74de05375121ac05dc403ea','same preserved physical initialization')
 need(x['physical_evaluations']==1 and x['accepted_fit_covariance'] is False and x['damping_values']==[0.,.001,1000.] and x['map_tolerance_posterior_sd']==1e-7 and x['relative_covariance_tolerance']==1e-8 and x['normalized_residual_energy_tolerance']==2e-12,'linearization fixed scope/limits')
 c=x['comparison'];d=npz(c['dense_reference']);R=d['factor'];b=d['rhs'];scales=d['scales'];dynamic=d['dynamic'].astype(bool);n=len(scales)
 need(0<n<=200 and R.shape==(n,n) and b.shape==(n,) and dynamic.shape==(n,) and np.isfinite(R).all() and np.isfinite(b).all() and np.all(scales>0),'finite original factor')
 singular=svdvals(R);t=np.finfo(float).eps*max(c['effective_rows'],n)*singular[0];need(singular[-1]>10*t,'original undamped rank resolved')
 inv=solve_triangular(R,np.eye(n));COV=scales[:,None]*(inv@inv.T)*scales[None,:];sd=np.sqrt(np.diag(COV));need(np.all(sd>0),'positive posterior scales');need(np.linalg.norm(COV-d['covariance'])/np.linalg.norm(COV)<1e-8 and np.allclose(sd,d['posterior_sd'],rtol=1e-11,atol=0),'dense covariance independent triangular solve')
 z0=solve_triangular(R,b);step0=scales*z0;const=c['dense_orthogonal_residual_energy'];need(math.isfinite(const) and const>=0,'orthogonal residual constant')
 profiles=[];need([p['segment_seconds'] for p in c['profiles']]==[3600,14400],'two cut layouts')
 for p in c['profiles']:
  need([a['damping'] for a in p['trials']]==[0.,.001,1000.] and p['covariance_optimization_damping']==0 and p['covariance_all_original_coordinates'] is True,'damping/covariance scope');trials=[]
  graph=json.loads(load(p['graph']));need(graph['native_original_columns']==n and graph['physical_propagation_split'] is False,'global propagation retained')
  for a in p['trials']:
   lam=a['damping'];penalty=np.sqrt(lam)*np.eye(n)[dynamic];design=np.vstack((R,penalty));target=np.concatenate((b,np.zeros(len(penalty))));z,_,rank,_=lstsq(design,target,lapack_driver='gelsy');need(rank==n,'damped numerical rank');expected=scales*z
   payload=json.loads(load(a['native_result']));need(payload['status']=='complete' and payload['step_coordinate_system']=='native' and payload['original_columns']==list(range(n)),'kernel original native-coordinate map');actual=np.asarray(payload['step'])[:n];need(actual.shape==(n,) and np.isfinite(actual).all(),'native original step');maperror=float(np.max(abs(actual-expected)/sd));need(maperror<1e-7 and finite(a['maximum_map_discrepancy_posterior_sd'],1e-7),'independent same-row MAP gate')
   energy=float(np.linalg.norm(b-R@z)**2+const+lam*np.linalg.norm(z[dynamic])**2);err=abs(payload['residual_energy']-energy)/max(1.,abs(energy));orth=abs(payload['orthogonal_residual_energy']-energy)/max(1.,abs(energy));need(max(err,orth)<2e-12 and same(energy,a['dense_residual_energy']) and same(payload['residual_energy'],a['segmented_residual_energy']),'complete residual energy')
   eq=payload['equality_max_backward_error'];need(finite(eq,2e-12) and eq==a['maximum_equality_backward_error'] and a['equality_residual_normalization']=='max_i |d_i-E_i*x| / (|d_i|+sum_j |E_ij*x_j|); zero denominator gives zero','separate fixed true equality gate')
   change=R@(actual/scales);prediction=float(b@change-.5*(change@change));need(same(prediction,a['segmented_predicted_reduction']) and a['dense_scaled_gradient']==a['segmented_scaled_gradient'],'same original objective model');trials.append({'damping':lam,'map_discrepancy_posterior_sd':maperror,'normalized_energy_difference':err,'normalized_orthogonal_energy_difference':orth,'kernel_equality_max_backward_error':eq})
  actual_cov=npz(p['covariance'])['covariance'];cov_error=float(np.linalg.norm(actual_cov-COV)/np.linalg.norm(COV));need(cov_error<1e-8 and finite(p['covariance_relative_error'],1e-8),'independent all-original covariance gate');profiles.append({'segment_seconds':p['segment_seconds'],'trials':trials,'covariance_relative_error':cov_error})
 oracle=c['independent_gtsam'];need(oracle['version']=='4.2' and oracle['elimination_api']=='JacobianFactor.eliminate(Ordering) -> EliminateQR','actual GTSAM QR provenance');o=npz(oracle['original_rows_and_result']);A=o['weighted_design'];y=o['weighted_target'];need(A.shape==(oracle['rows'],n) and y.shape==(len(A),) and oracle['columns']==n and np.array_equal(o['column_scales'],scales),'oracle original rows identity');scaled=A*scales;Q,T=qr(scaled,mode='economic');z=solve_triangular(T,Q.T@y);expected=scales*z;Ti=solve_triangular(T,np.eye(n));oracle_cov=scales[:,None]*(Ti@Ti.T)*scales[None,:];indmap=float(np.max(abs(expected-step0)/sd));indcov=float(np.linalg.norm(oracle_cov-COV)/np.linalg.norm(COV));gmap=float(np.max(abs(o['step']-step0)/sd));gcov=float(np.linalg.norm(o['covariance']-COV)/np.linalg.norm(COV));energy=float(np.linalg.norm(y-A@o['step'])**2);dense_energy=float(np.linalg.norm(b-R@z0)**2+const);err=abs(energy-dense_energy)/max(1.,abs(dense_energy));need(max(indmap,gmap)<1e-7 and max(indcov,gcov)<1e-8 and err<2e-12,'independent original-row QR/GTSAM agreement');need(same(energy,oracle['full_residual_energy']),'oracle energy report')
 for key,limit in [('maximum_equality_substitution_residual',2e-12),('maximum_map_discrepancy_posterior_sd',1e-7),('covariance_relative_error',1e-8),('normalized_residual_energy_difference',2e-12)]:need(finite(oracle[key],limit),'GTSAM reported criterion '+key)
 prior=x['prior'];need(prior['cost']>0 and prior['rows'] in (6,61) and prior['maximum_residual_difference']<=prior['absolute_tolerance'],'nonzero native prior')
 return {'physical_evaluations':1,'original_columns':n,'effective_rows':c['effective_rows'],'undamped_rank':{'smallest_singular_value':float(singular[-1]),'deficiency_threshold':float(t),'unresolved_threshold':float(10*t),'resolved':True},'profiles':profiles,'gtsam':{'version':'4.2','original_rows':len(A),'map_discrepancy_posterior_sd':gmap,'covariance_relative_error':gcov,'independent_scipy_original_row_qr_map_discrepancy_posterior_sd':indmap,'independent_scipy_original_row_qr_covariance_relative_error':indcov,'normalized_full_energy_difference':err,'maximum_equality_substitution_residual':oracle['maximum_equality_substitution_residual']},'prior':prior,'covariance_scope':'Undamped linearization covariance only; no accepted fit covariance.','cut_scope':x['cut_scope'],'equality_audit_scope':'Pinned native solve payloads enforce the fixed backward-error threshold; solver equality arithmetic has separate structural tests. This audit independently recomputes MAP, covariance, rank and full energy from captured arrays.'}

def audit(capture,arrays):
 cap=json.loads((capture/'manifest.json').read_bytes());raw={};pins={};stored=set()
 need(cap['schema']=='orbit-poc-v4-terminal-validation-capture-v1','capture schema')
 for rec in cap['records']:
  relative=Path(rec['stored']['path']);need(not relative.is_absolute() and '..' not in relative.parts,'unsafe capture path')
  p=capture/relative;b=p.read_bytes();need(len(b)==rec['stored']['bytes'] and sha(b)==rec['stored']['sha256'],'stored hash')
  b=gzip.decompress(b) if rec['encoding']=='gzip' else b
  need(len(b)==rec['source']['bytes'] and sha(b)==rec['source']['sha256'],'raw hash')
  path=rec['source']['path'];need(path not in raw and str(relative) not in stored,'duplicate capture')
  raw[path]=b;pins[path]=rec['source'];stored.add(str(relative))
 need({str(p.relative_to(capture)) for p in capture.rglob('*') if p.is_file() and p!=capture/'manifest.json'}==stored,'capture membership')
 array_manifest=json.loads((arrays/'manifest.json').read_bytes());need(array_manifest['schema']=='orbit-poc-segmented-linearization-array-capture-v1' and len(array_manifest['records'])==8,'eight-array appendix schema')
 need(array_manifest['main_capture']['sha256']==pin(capture/'manifest.json')['sha256'] and array_manifest['pipeline']==cap['pipeline'],'array/main exact attribution')
 array_members=set()
 for rec in array_manifest['records']:
  relative=Path(rec['stored']['path']);need(not relative.is_absolute() and '..' not in relative.parts,'unsafe array path');b=(arrays/relative).read_bytes();need(sha(b)==rec['stored']['sha256']==rec['source']['sha256'] and len(b)==rec['stored']['bytes']==rec['source']['bytes'],'array bytes');path=rec['source']['path'];need(path not in raw or raw[path]==b,'array duplicate conflict');raw[path]=b;pins[path]=rec['source'];array_members.add(str(relative))
 need({str(p.relative_to(arrays)) for p in arrays.rglob('*') if p.is_file() and p!=arrays/'manifest.json'}==array_members,'array appendix membership')
 def data(path):return json.loads(raw[path])
 def checked(p):
  need(p['path'] in raw,'missing pinned evidence '+p['path']);need(sha(raw[p['path']])==p['sha256'],'pinned digest');return data(p['path'])
 def under(rel):return R+'/'+rel
 paths={'controller':under('control/validation-controller.json'),'cli_pipeline':cap['pipeline']['path'],'validation_context':under('run/validation/context.json'),'validation_plan':under('run/validation/plan.json'),'run_plan':under('run/plan.json'),'config':under('control/segmented-v4.json'),'source_freeze':under('control/source-freeze.json'),'launch_plan':under('control/launch-plan.json'),'launch_pins':under('control/launch-pins.json')}
 v={k:data(p) for k,p in paths.items()};controller=v['controller'];pipeline=v['cli_pipeline'];context=v['validation_context'];vp=v['validation_plan'];rp=v['run_plan'];freeze=v['source_freeze']
 for name,h in [('config','e23eb3a1b4eafc6c1c279183292513b87e64a366061ac6ef645987700c193fac'),('source_freeze','87ad55dcd0c4329cb4e37a37adfe3871cb85d3fb88e8a46b3cff388aa17e9f29'),('launch_plan','0a5c65a31b0e8db192a99c29018ab391eb22d81e26f9ce66c77ea164092b07c7'),('launch_pins','4b0467351c96859874e78569ad626baddda98902e3206770814516a34d14bd24')]:need(pins[paths[name]]['sha256']==h,'actual frozen '+name)
 for value,key in [(rp,'plan_hash'),(vp,'plan_hash'),(context,'validation_context_hash')]:need(value[key]==canonical({k:x for k,x in value.items() if k!=key}),'canonical identity')
 need(context['plan_hash']==rp['plan_hash'] and vp['validation_context_hash']==context['validation_context_hash']==pipeline['validation_context_hash'] and pipeline['plan_hash']==vp['plan_hash'],'cross plan identity')
 need(freeze['source']['sha256']==FULL and len(freeze['source']['files'])==384 and freeze['comparison_source']['sha256']==COMPARISON==rp['source']['sha256'],'source identity')
 need(controller['source']==freeze['source'] and controller['plan']==pins[paths['launch_plan']],'controller exact source/launch attribution')
 cli=controller['cli_validation'];need(cli['pipeline']['path']==paths['cli_pipeline'] and cli['pipeline']['sha256']==pins[paths['cli_pipeline']]['sha256'] and cli['planned']==14 and cli['passed']==14 and cli['status']=='passed','controller exact CLI attribution')
 need(controller['returncode']==0 and controller['interrupted_or_timeout'] is False and controller['release_ready'] is False,'outer terminal outcome')
 argv=controller['argv'];need(argv[argv.index('--execution-sha256')+1]=='526e8f704650eccc69863669ac4068c1c192f38b990a5a2190eba81d4a22007d' and argv[-3:]==['validate','--config',paths['config']],'reviewed execution and actual public entrypoint')
 rt=context['runtimes']['segmented'];need(rt['source_sha256']==COMPARISON and rt['native']['sha256']==NATIVE and rt['segmented_solver']['sha256']==SOLVER,'runtime identity')
 need(controller['status']=='passed' and pipeline['status']=='passed','expected actual passed journals')
 need(controller['final_cleanup']['verified'] and not controller['final_cleanup']['errors'],'outer cleanup')
 for command in controller['final_cleanup']['commands']:need(command['verified'] and not command['live_owned_processes'],'owned live cleanup')
 need([s['name'] for s in pipeline['steps']]==STAGES==vp['stages'],'stage registry')
 need([s['status'] for s in pipeline['steps']]==['passed']*14,'actual status inventory')
 need(cap['benchmark_outputs']['manifest_present'] is False and cap['benchmark_outputs']['attempts_directory_present'] is False and cap['benchmark_outputs']['attempt_entries']==[],'benchmark absent')
 need(len(rp['cases'])==28 and len(rp['attempts'])==68 and len({a['attempt_id'] for a in rp['attempts']})==68,'benchmark inventory')
 reference_path=SOURCE/'src/orbit_poc/segmented/validation_reference.py';reference_entry=next(x for x in freeze['source']['files'] if x['path']=='src/orbit_poc/segmented/validation_reference.py');need(pin(reference_path)['sha256']==reference_entry['sha256'],'immutable native/correction inventory source');tree=ast.parse((SOURCE/'src/orbit_poc/segmented/validation_reference.py').read_text());inventories=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TEST_INVENTORIES' for t in n.targets))
 need(vp['validation_inputs']['sha256']=='50d9d05d275d48f6039a9478397c5470e9391ca32e53ed67c7d6b32d2bd0edb4','original14 inventory identity')
 results=[]
 for index,step in enumerate(pipeline['steps']):
  name=step['name'];directory=step['directory'];art=[];measure={}
  need(directory==str(Path(paths['cli_pipeline']).parent/name),'stage directory')
  if 'execution' in step:
   e=checked(step['execution']);art.append(pins[step['execution']['path']]);q=data(directory+'/request.json');art.append(pins[directory+'/request.json']);need(e['argv']==q['argv'],'native argv')
   h=e['harness_execution'];clean=h['cleanup'];need(h['owned_process_group_cleaned'] and clean['verified'] and clean['empty_tree_certificate']=='kernel_ECHILD' and not clean['remaining'],'kernel owned cleanup')
   need(h['runtime']['source_sha256']==COMPARISON and h['runtime']['native']['sha256']==NATIVE,'stage runtime')
   if step['status']=='passed':need(e['status']=='complete' and e['returncode']==0,'passed execution')
  if index<2:
   j=step['evidence']['junit'];checked_bytes=raw[j['path']];need(sha(checked_bytes)==j['sha256'],'JUnit hash');cases=ET.fromstring(checked_bytes).findall('.//testcase');key='original_native_tests' if index==0 else 'correctness_tests'
   actual=[{'classname':x.get('classname',''),'name':x.get('name','')} for x in cases];need(actual==inventories[key],'protected original JUnit identity');need(all(x.find('error') is None and x.find('failure') is None and x.find('skipped') is None for x in cases),'JUnit status');art.append(pins[j['path']]);measure={'passed':len(cases),'failures':0,'errors':0,'skipped':0,'exact_original_inventory':True}
  elif index<6:
   p=step['evidence']['result'];x=checked(p);art.append(pins[p['path']]);need(x['passed'] and x['status']=='complete' and x['binary_sha256']==NATIVE,'refinement identity');signals=x['native_signals']['signals'];need(signals and all(0<=s['maximum_fraction_of_sigma']<.01 for s in signals),'refinement');need(x['metrics'] and all(0<=a<3e-5 for a in x['metrics'].values()),'refinement metrics');measure={'maximum_fraction_of_sigma':max(s['maximum_fraction_of_sigma'] for s in signals),'metrics':x['metrics']}
  elif index<8:
   p=step['evidence']['result'];x=checked(p);art.append(pins[p['path']]);need(x['passed'] and x['native_binary_sha256']==NATIVE and x['source_hash']==COMPARISON,'objective identity');density=index==6;prior=x['prior'];tol=2e-8 if density else 1e-12
   need(prior['rows']==(61 if density else 6) and prior['source']==('constraint.logDensityOu' if density else 'constraint.pulses') and prior['absolute_tolerance']==tol and 0<=prior['maximum_residual_difference']<=tol and 0<prior['cost']<prior['objective'],'full nonzero prior')
   need(x['derivative_refinement_policy']=={'maximum_scales':9,'physical_repeat_allowance_multiplier':10,'ratio':.5,'required_consecutive_passing_scales':2} and x['relative_derivative_tolerance']==1e-4,'fixed objective limits')
   physical=x['empirical_physical_objective_resolution'];need(physical>=10*x['objective_repeat_difference']>=0,'repeat allowance');streak=[];scales=[]
   for i,d in enumerate(x['directional_derivatives']):
    s=d['scale'];need(s==.5**i,'scale schedule');fd=(d['positive_cost']-d['negative_cost'])/(2*s);need(close(fd,d['finite_difference']),'finite difference');den=max(abs(fd),abs(d['native_derivative']),1e-12);checks=d['endpoint_resolution_checks'];need(len(checks)==2 and {a['sign'] for a in checks}=={-1,1},'endpoint support')
    for a in checks:
     cost=d['negative_cost'] if a['sign']==-1 else d['positive_cost'];need(close(abs(cost-a['repeat_cost']),a['repeat_difference']) and a['empirical_resolution']>=max(physical,10*a['repeat_difference']),'endpoint repeat')
    error=abs(fd-d['native_derivative'])/den+sum(a['empirical_resolution'] for a in checks)/(2*s*den);passed=error<=1e-4;need(close(error,d['relative_difference_plus_resolution']) and passed==d['passes_unchanged_tolerance'],'objective arithmetic');streak=streak+[s] if passed else [];scales.append({'scale':s,'error_plus_resolution':error,'passed':passed})
   need(len(streak)>=2 and streak[-2:]==x['accepted_derivative_scales']==step['evidence']['accepted_scales'],'two consecutive scales');updates=[]
   for profile in x['profile_evaluations']:
    pp=profile['receipt'];d=data(pp);art.append(pins[pp]);need(d['nuisance_converged'] and not d['nuisance_floor_limited'] and d['nuisance_floor_audit']==[] and d['nuisance_objective_resolution']==0,'strict nuisance');need(d['fixed_weights'] and not d['dynamic_updates'] and d['threshold_m']==1e-8 and d['required_consecutive_small_updates']==2,'profile policy');need(len(d['history'])==d['iterations'] and len(d['history'])>=2 and all(0<=a['maximum_update_m']<1e-8 for a in d['history'][-2:]),'strict history');updates.append(d['maximum_update_m'])
   measure={'full_nonzero_prior':prior,'strict_profiles':len(updates),'floor_limited_profiles':0,'maximum_strict_nuisance_update_m':max(updates),'directional_scales':scales,'accepted_consecutive_scales':streak[-2:],'physical_repeat_difference':x['objective_repeat_difference'],'empirical_physical_objective_resolution':physical,'resolution_scope':x['resolution_scope']}
  elif index<10:
   p=step['evidence']['result'];x=checked(p);art.append(pins[p['path']]);measure=replay_check(x,directory,raw,pins,index,art)
  elif index<12:
   p=step['evidence']['junit'];b=raw[p['path']];need(sha(b)==p['sha256'],'v4 JUnit hash');cases=ET.fromstring(b).findall('.//testcase');actual=[(x.get('classname',''),x.get('name','')) for x in cases];need(len(actual)==len(set(actual)) and len(cases)==(3 if index==10 else 303),'v4 exact test count/uniqueness');need(all(all(x.find(k) is None for k in ('failure','error','skipped')) for x in cases),'v4 JUnit status');art.append(pins[p['path']])
   if index==11:
    expected={'test_segmented_native_qr','test_segmented_graph','test_segmented_linear_system','test_segmented_solver','test_segmented_tangent','test_segmented_diagnostics','test_segmented_linearization_gate','test_numerics_optimizer','test_segmented_protocol','test_segmented_multiday','test_segmented_validation','test_segmented_products','test_segmented_supervisor','test_segmented_backend','test_segmented_engineering'};need({a.split('.')[-1] for a,b in actual}==expected,'all structural modules');prior_review_path=C/'segmented-validation03-terminal-independent-review-01.json';need(pin(prior_review_path)['sha256']=='3df121d1b3142eb4814ce557a24991acc3388813d43178499732bd7422c1daee','prior audited structural inventory pin');old_inventory=json.loads(prior_review_path.read_bytes())['stages'][11]['measurements']['complete_inventory'];old_pairs=[tuple(v) for v in old_inventory];added=[('tests.test_segmented_multiday','test_prepare_one_selects_corrected_profile_through_shared_closure['+method+']') for method in ('groops_pulses','groops_log_drag_ou')];need(len(old_pairs)==301 and len(set(old_pairs))==301 and set(actual)==set(old_pairs+added),'original301 structural inventory plus exact two approved regressions')
   measure={'passed':len(cases),'failures':0,'errors':0,'skipped':0,'complete_inventory':actual}
  else:
   p=step['evidence']['result'];x=checked(p);art.append(pins[p['path']]);measure=linearization_check(x,raw,pins,art,index)
  results.append({'name':name,'status':step['status'],'raw_artifacts':art,'measurements':measure,'independently_consistent':True})
 return {'schema':'orbit-poc-segmented-validation-terminal-independent-review-v1','reviewer':'/root/v4_independent_review','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'consistency_passed':True,'scientific_status':'passed_scoped_checks','cleanup_verified':True,'release_ready':False,'fit_covariance_authorized':False,'benchmark_attempts_executed':0,'identity':{'full_source_sha256':FULL,'comparison_source_sha256':COMPARISON,'source_file_count':384,'native_sha256':NATIVE,'solver_sha256':SOLVER},'artifacts':{k:pins[p] for k,p in paths.items()},'stages':results,'capture':pin(capture/'manifest.json'),'limitations':['These are bounded correctness gates, not completed benchmark fits or an accuracy/speed claim.','One-hour native linearization fixtures do not establish interior one-hour/four-hour cut equivalence; separately pinned shifted-cut diagnostics remain required.','Strict nuisance stationarity coexists with measured physical objective repeat spread; unchanged ten-times resolution allowances remain included.','All 68 benchmark fits remain unrun; no accepted-fit covariance or release approval is inferred.'],'supporting_reviews':[pin(C/'validation04-packet-independent-review01/review.json'),pin(C/'validation04-actual-startup-independent-review01.json'),pin(C/'validation04-launch-independent-review04.json')],'audit_helper':pin(__file__)}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--capture',type=Path,required=True);p.add_argument('--arrays',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=audit(a.capture,a.arrays);r['array_capture']=pin(a.arrays/'manifest.json');r['actual_owned_process_absence']=pin(C/'validation04-independent-cleanup-01/result.json');clean=json.loads(Path(r['actual_owned_process_absence']['path']).read_bytes());need(clean['passed'] and not clean['live_exact_owned'] and clean['controller']==r['artifacts']['controller'],'fresh owned absence attribution');a.output.open('x').write(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps(pin(a.output)))
