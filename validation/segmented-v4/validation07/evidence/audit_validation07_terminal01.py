#!/usr/bin/env python3
"""Independent, scoped audit of the completed validation07 gates; no execution."""
from pathlib import Path
import argparse,ast,datetime,gzip,hashlib,json,math,xml.etree.ElementTree as ET
R='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07'
C=Path('/mnt/d/orbit-segmented-v4/control')
SOURCE=Path('/mnt/d/orbit-segmented-v4/validation-07-packet/source')
STAGES=['native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses']
NATIVE='643a1b6d523a363eae88902f2a2d4807452ea3edbd504bceaad23a94d65fb2f6'
SOLVER='2c8481050806ce9d4c89d4c605fd9036bed3cdfb97010efeb359213aa0dbc223'
FULL='9f37ce4fbd8484e1c0f16caa742670b42d9d08a639c036bded66403c2708ec8a'
COMPARISON='a838553d4ba9dc394a3f498f46917275b19139d2bb583c401cf71e90f82a9fa6'
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
 need(x['build_manifest_sha256']=='f4209ee2011d7c566c1d51189745140155ebaf455db32d2999172f542ca15ec8','actual complete-build sidecar')
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


SUPPORT={
 'validation07-independent-concrete-packet-review01.json':'65ab7044d94fecfd97490b101ec51e64dbc1c92bcbb70e879f2a714c5ef26e98',
 'validation07-host-precheck-independent-review01.json':'2f99c9166778b3d7881e010d9441025a8ccd0729c1ff49d4373d5bfa732ed264',
 'validation07-actual-startup-independent-review01.json':'9e7dd602a3430a9bd05b2c0ee7de1f937c6215c20e88f2e365a306d4deb8c017',
 'validation07-launch-independent-review01.json':'8a2c1a155560c377cd1afc31e5e9a7430e5eb5efaafccba9cbebe08c8760b05b',
 'native-complete-build02-independent-terminal-review01.json':'4fcbcd598dd41b4b53466393118d8ff626a88f8a79ff2b95c8b0c6f9eb3dfc6e'
}
def supporting_reviews():
 result=[]
 for name,h in SUPPORT.items():
  p=C/name;record=pin(p);need(record['sha256']==h and json.loads(p.read_bytes()).get('passed') is True,'supporting actual review changed: '+name);result.append(record)
 return result

def verify_complete_provenance(provenance,freeze,config,context,launch,accepted_build):
 """Bind previously audited complete build to this fresh source/runtime; no scientific pass inherited."""
 need(provenance['schema']=='orbit-poc-v4-native-rebuild-provenance-v3' and provenance['status']=='verified_actual_complete_rebuild','complete build provenance schema/status')
 need(accepted_build.get('passed') is True and accepted_build['schema']=='orbit-poc-native-complete-build-independent-review-v1','accepted actual complete build')
 expected_counts={'compiled_objects':611,'cpp_objects':591,'fortran_objects':20,'fortran_preprocessing':20,'complete_commands':633,'reused_objects':0,'full_source_files':1134}
 need(all(accepted_build[k]==v for k,v in expected_counts.items()),'full fresh build counts')
 need(provenance['actual_build_result']==accepted_build['actual_build_result']=={'path':R.replace('/validation-07','/native-complete-build-02')+'/run/build-result/result.json','sha256':'0513e768a7e85fbc75cef08ccedde923563980b3e2ff4dc03d48d986526615f2'},'actual completed build result binding')
 for key in ('original_recipe_inventory','normalized_configuration','complete_compile_evidence','baseline_relink','installation_equivalence'):
  need(provenance[key]==accepted_build[key],'complete build artifact binding: '+key)
 need(provenance['native_source_delta']==accepted_build['source_delta'] and provenance['build_base_result']==accepted_build['baseline_result'] and provenance['build_base_result']['sha256']=='92dcf754ad42ad22c92b0e0413e86af83fd7d4f9700b69c08c86254022e69224','separate actual precision02 build baseline and installed delta')
 need(provenance['previous_source']==freeze['previous_source']=={'path':R.replace('/validation-07','/validation-05')+'/control/source-freeze.json','sha256':'87b220cf9a66737e72ed2037c3a80895eb445bf3058918fad32d38e79df8078c'},'previous validation source stays distinct from build baseline')
 need(provenance['previous_config']=={'path':R.replace('/validation-07','/validation-05')+'/control/segmented-v4.json','sha256':'d7d66e175353213889ce32d8606a572d219bc2138ad58f1041558e49b014486b'},'previous config identity')
 need(provenance['runtime_provenance']=={'path':R.replace('/validation-07','/runtime-complete-01')+'/provenance.json','sha256':'01f15436a0c1e7d9f008e2dd3c795fbe0b34f524f7a408c180cfaa8bb3e02bfc'},'exact relocated runtime lineage')
 files=freeze['source']['files'];need(len(files)==405 and canonical(files)==FULL==freeze['source']['sha256'],'complete405-source inventory')
 need(freeze['allowed_changed_paths']==['groops/extension/sixStateTangent.h','scripts/build_groops.py','tests/test_segmented_native_tangent.py'] and freeze['additional_paths']==ADDITIONS,'explicit three replacements and21 additions')
 need(provenance['repository_source_delta']==freeze['repository_source_delta'] and provenance['repository_source_delta']==REPOSITORY_DELTA,'exact repository delta binding')
 need(provenance['native_inputs']=={k:h for k,h in files.items()if k.startswith('groops/')or k=='scripts/build_groops.py'} and len(provenance['native_inputs'])==79 and provenance['fixed_stage_names']==STAGES,'current79 native source inputs and unchanged14-stage registry')
 need(provenance['installed_source_mapping']==INSTALLED_MAPPING and provenance['candidate_native_source_root']==R.replace('/validation-07','/native-complete-build-02')+'/native_source/candidate/source','seven installed payload paths')
 need(files['groops/extension/sixStateTangent.h']=='9a46f04591de8b8956cb6af0888936ace7f35688cef778861a99a859a65cdef0' and files['groops/extension/wide_tangent/proposed/misc/orbitPoc/wideSixStateTangent.h']=='b6910fec1dfe65ce0541d41e6448e2515a72cf94c94232de79d5bcf01aa1d263','explicit compensated and wide headers')
 need(context['runtimes']['dense']['native']['sha256']==config['dense_runtime']['native']['sha256']=='f36bb698ea715a7fc3201c71f823315d493d943ecfb8e7ecad8fbb348ba61625','preserved dense reference')
 need(context['runtimes']['segmented']['native']==config['segmented_runtime']['native'] and config['segmented_runtime']['native']['sha256']==accepted_build['native']['sha256']==NATIVE,'actual complete candidate identity')
 need(config['segmented_runtime']['build_manifest']['sha256']==accepted_build['build_manifest']['sha256']=='f4209ee2011d7c566c1d51189745140155ebaf455db32d2999172f542ca15ec8','exact original public build manifest')
 need(launch['native_equivalence']=={'path':R+'/control/native-rebuild-provenance.json','sha256':'54d7fc89aa85a51f3dca4f2cc64f31427fc87a94381658e5f7c7b2bbe5f92b19'},'launch complete provenance binding')
 return True

ADDITIONS=['groops/extension/native_tangent_wide.py', 'groops/extension/wide_tangent/manifest.json', 'groops/extension/wide_tangent/proposed/base/polynomial.cpp', 'groops/extension/wide_tangent/proposed/misc/orbitPoc/piecewisePolynomial.h', 'groops/extension/wide_tangent/proposed/misc/orbitPoc/stagedVariationalBody.h', 'groops/extension/wide_tangent/proposed/misc/orbitPoc/wideInterpolationExport.h', 'groops/extension/wide_tangent/proposed/misc/orbitPoc/wideInterpolationStencil.h', 'groops/extension/wide_tangent/proposed/misc/orbitPoc/wideSixStateTangent.h', 'groops/extension/wide_tangent/proposed/programs/preprocessing/preprocessingVariationalEquation.cpp', 'src/orbit_poc/segmented/tangent_export.py', 'tests/fixtures/tangent_compensated_quadrature.cpp', 'tests/fixtures/wide_interpolation_export_fixture.cpp', 'tests/fixtures/wide_interpolation_fixture.cpp', 'tests/fixtures/wide_tangent_baseline/base/polynomial.cpp', 'tests/fixtures/wide_tangent_baseline/misc/orbitPoc/piecewisePolynomial.h', 'tests/fixtures/wide_tangent_baseline/misc/orbitPoc/stagedVariationalBody.h', 'tests/fixtures/wide_tangent_baseline/programs/preprocessing/preprocessingVariationalEquation.cpp', 'tests/test_numerics_compensated_quadrature.py', 'tests/test_segmented_tangent_export.py', 'tests/test_wide_tangent_install.py', 'tests/test_wide_tangent_native.py']
INSTALLED_MAPPING={'base/polynomial.cpp': 'groops/extension/wide_tangent/proposed/base/polynomial.cpp', 'misc/orbitPoc/piecewisePolynomial.h': 'groops/extension/wide_tangent/proposed/misc/orbitPoc/piecewisePolynomial.h', 'misc/orbitPoc/stagedVariationalBody.h': 'groops/extension/wide_tangent/proposed/misc/orbitPoc/stagedVariationalBody.h', 'misc/orbitPoc/wideInterpolationExport.h': 'groops/extension/wide_tangent/proposed/misc/orbitPoc/wideInterpolationExport.h', 'misc/orbitPoc/wideInterpolationStencil.h': 'groops/extension/wide_tangent/proposed/misc/orbitPoc/wideInterpolationStencil.h', 'misc/orbitPoc/wideSixStateTangent.h': 'groops/extension/wide_tangent/proposed/misc/orbitPoc/wideSixStateTangent.h', 'programs/preprocessing/preprocessingVariationalEquation.cpp': 'groops/extension/wide_tangent/proposed/programs/preprocessing/preprocessingVariationalEquation.cpp'}
REPOSITORY_DELTA={'path': '/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07/control/repository-source-delta.json', 'sha256': '9469b3570bc2043878c46d38d11125176aa5b00c6051df800abc8c59177a2b70'}

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
 paths={'controller':under('control/validation-controller.json'),'cli_pipeline':cap['pipeline']['path'],'validation_context':under('run/validation/context.json'),'validation_plan':under('run/validation/plan.json'),'run_plan':under('run/plan.json'),'config':under('control/segmented-v4.json'),'source_freeze':under('control/source-freeze.json'),'launch_plan':under('control/launch-plan.json'),'launch_pins':under('control/launch-pins.json'),'native_rebuild_provenance':under('control/native-rebuild-provenance.json')}
 v={k:data(p) for k,p in paths.items()};controller=v['controller'];pipeline=v['cli_pipeline'];context=v['validation_context'];vp=v['validation_plan'];rp=v['run_plan'];freeze=v['source_freeze']
 for name,h in [('config','33cf305ada15863e2ee04e57390707344ed045a9fc712efc3f5e6e9247656378'),('source_freeze','3e592667266642e4a8955f1f1c046a7eabb49c80aaa3b7c2ef43bb59969c5b1d'),('launch_plan','7ed449091ce94adabdbf7a5d111f357194bb742e6615e5aa4e64b6e43d84a27f'),('launch_pins','9c6a2a5940c5771799187263f41f536a61ec16b87703887d34083479c3ef0cad')]:need(pins[paths[name]]['sha256']==h,'actual frozen '+name)
 for value,key in [(rp,'plan_hash'),(vp,'plan_hash'),(context,'validation_context_hash')]:need(value[key]==canonical({k:x for k,x in value.items() if k!=key}),'canonical identity')
 need(context['plan_hash']==rp['plan_hash'] and vp['validation_context_hash']==context['validation_context_hash']==pipeline['validation_context_hash'] and pipeline['plan_hash']==vp['plan_hash'],'cross plan identity')
 need(freeze['source']['sha256']==FULL and len(freeze['source']['files'])==405 and freeze['comparison_source']['sha256']==COMPARISON==rp['source']['sha256'],'source identity')

 provenance=v['native_rebuild_provenance'];need(pins[paths['native_rebuild_provenance']]['sha256']=='54d7fc89aa85a51f3dca4f2cc64f31427fc87a94381658e5f7c7b2bbe5f92b19','exact reviewed complete native provenance')
 build_review_path=C/'native-complete-build02-independent-terminal-review01.json';need(pin(build_review_path)['sha256']==SUPPORT[build_review_path.name],'accepted complete build review identity');build_review=json.loads(build_review_path.read_bytes())
 verify_complete_provenance(provenance,freeze,v['config'],context,v['launch_plan'],build_review)
 need(controller['source']==freeze['source'] and controller['plan']==pins[paths['launch_plan']],'controller exact source/launch attribution')
 cli=controller['cli_validation'];need(cli['pipeline']['path']==paths['cli_pipeline'] and cli['pipeline']['sha256']==pins[paths['cli_pipeline']]['sha256'] and cli['planned']==14 and cli['passed']==14 and cli['status']=='passed','controller exact CLI attribution')
 need(controller['returncode']==0 and controller['interrupted_or_timeout'] is False and controller['release_ready'] is False,'outer terminal outcome')
 argv=controller['argv'];need(argv[argv.index('--execution-sha256')+1]=='8865f43a1d2b03ca194252dfd21670c664f55aa006088ad98ed75c1ca7ffe8ae' and argv[-3:]==['validate','--config',paths['config']],'reviewed execution and actual public entrypoint')
 rt=context['runtimes']['segmented'];need(rt['source_sha256']==COMPARISON and rt['native']['sha256']==NATIVE and rt['segmented_solver']['sha256']==SOLVER,'runtime identity')
 need(controller['status']=='passed' and pipeline['status']=='passed','expected actual passed journals')
 need(controller['final_cleanup']['verified'] and not controller['final_cleanup']['errors'],'outer cleanup')
 for command in controller['final_cleanup']['commands']:need(command['verified'] and not command['live_owned_processes'],'owned live cleanup')
 need([s['name'] for s in pipeline['steps']]==STAGES==vp['stages'],'stage registry')
 need([s['status'] for s in pipeline['steps']]==['passed']*14,'actual status inventory')
 need(cap['benchmark_outputs']['manifest_present'] is False and cap['benchmark_outputs']['attempts_directory_present'] is False and cap['benchmark_outputs']['attempt_entries']==[],'benchmark absent')
 need(len(rp['cases'])==28 and len(rp['attempts'])==68 and len({a['attempt_id'] for a in rp['attempts']})==68,'benchmark inventory')
 reference_path=SOURCE/'src/orbit_poc/segmented/validation_reference.py';reference_entry=freeze['source']['files']['src/orbit_poc/segmented/validation_reference.py'];need(pin(reference_path)['sha256']==reference_entry,'immutable native/correction inventory source');tree=ast.parse((SOURCE/'src/orbit_poc/segmented/validation_reference.py').read_text());inventories=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TEST_INVENTORIES' for t in n.targets))
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
 return {'schema':'orbit-poc-segmented-validation-terminal-independent-review-v1','reviewer':'/root/v4_independent_review','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'consistency_passed':True,'scientific_status':'passed_scoped_checks','cleanup_verified':True,'release_ready':False,'fit_covariance_authorized':False,'benchmark_attempts_executed':0,'identity':{'full_source_sha256':FULL,'comparison_source_sha256':COMPARISON,'source_file_count':405,'native_sha256':NATIVE,'solver_sha256':SOLVER},'artifacts':{k:pins[p] for k,p in paths.items()},'stages':results,'capture':pin(capture/'manifest.json'),'limitations':['These are bounded correctness gates, not completed benchmark fits or an accuracy/speed claim.','One-hour native linearization fixtures do not establish interior one-hour/four-hour cut equivalence; separately pinned shifted-cut diagnostics remain required.','Strict nuisance stationarity coexists with measured physical objective repeat spread; unchanged ten-times resolution allowances remain included.','All 68 benchmark fits remain unrun; no accepted-fit covariance or release approval is inferred.'],'supporting_reviews':supporting_reviews(),'audit_helper':pin(__file__)}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--capture',type=Path,required=True);p.add_argument('--arrays',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=audit(a.capture,a.arrays);r['array_capture']=pin(a.arrays/'manifest.json');r['actual_owned_process_absence']=pin(C/'validation07-independent-cleanup-01/result.json');clean=json.loads(Path(r['actual_owned_process_absence']['path']).read_bytes());need(clean['passed'] and not clean['live_exact_owned'] and clean['controller']==r['artifacts']['controller'],'fresh owned absence attribution');a.output.open('x').write(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps(pin(a.output)))
