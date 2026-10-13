from pathlib import Path
import importlib.util,json,gzip,shutil
from orbit_poc.comparison.data import write_json,sha256_file
spec=importlib.util.spec_from_file_location('nuisance','outputs/orbit-smoothing-poc/validation/comparison-v3/evaluate_nuisance_recovery.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
base=Path('/tmp/orbit-v3-nuisance-mapping-74863');target=Path('outputs/orbit-smoothing-poc/validation/comparison-v3');records=[];archives=[];raw=target/'nuisance-mapping-74863';raw.mkdir(exist_ok=True)
for case in ['normal','masked']:
 for method in ['groops_pulses','groops_log_drag_ou']:
  directory=base/case/method;request=json.loads((directory/'request.json').read_text());fit=json.loads((directory/'result.json').read_text())
  output=directory/'native-fit/output/2024-04-24'
  r=mod.assess(output,base/'generation',base/'data_manifest.json',mask=request['case']['mask'])
  assert fit['native_binary_sha256']==sha256_file(base/'groops')
  events=[e for e in r['slips'] if e['estimated_jump_error_m'] is not None]
  r.update(case=case,method=method,converged=fit['converged'],covariance_valid=fit['covariance_valid'],
    source_hash=request['source_hash'],native_binary_sha256=fit['native_binary_sha256'],
    request_sha256=sha256_file(directory/'request.json'),result_sha256=sha256_file(directory/'result.json'),
    preprocessing_audit_sha256=fit['preprocessing_audit_sha256'],
    retained_two_sided_slips=len(events),raw_visible_two_sided_slips=sum(e['raw_two_sided_30s_visibility'] for e in r['slips']),
    maximum_IF_slip_jump_error_m=max([abs(e['estimated_jump_error_m']) for e in events],default=0.),
    all_retained_two_sided_slips_segmented=all(e['status']=='segmented' for e in events),
    no_retained_track_crosses_any_injected_slip=not any(e['retained_track_crosses_slip'] for e in r['slips']))
  r['mapping_check_passed']=bool(r['converged'] and r['clock']['gauge_aligned_max_abs_m']<.002 and r['phase']['gauge_aligned_max_abs_m']<.002 and r['maximum_IF_slip_jump_error_m']<.002 and r['all_retained_two_sided_slips_segmented'] and r['no_retained_track_crosses_any_injected_slip'] and not r['phase']['missing_truth_matches'])
  records.append(r)
  print(case,method,'clock rms/max',r['clock']['gauge_aligned_rms_m'],r['clock']['gauge_aligned_max_abs_m'],'IF rms/max',r['phase']['gauge_aligned_rms_m'],r['phase']['gauge_aligned_max_abs_m'],'jump',r['maximum_IF_slip_jump_error_m'],'PASS',r['mapping_check_passed'])
  for name in ['phase_recovery.txt','receiver_clock.txt']:
   p=output/name;archive=raw/f'{case}__{method}__{name}.gz'
   with p.open('rb') as source,gzip.open(archive,'wb') as destination:shutil.copyfileobj(source,destination)
   archives.append({'source_label':f'{case}/{method}/{name}','source_sha256':sha256_file(p),'archive':archive.name,'sha256':sha256_file(archive)})
for name in ['ambiguity_truth.txt','simulated_clock.txt']:
 p=base/'generation'/name;archive=raw/(name+'.gz')
 with p.open('rb') as source,gzip.open(archive,'wb') as destination:shutil.copyfileobj(source,destination)
 archives.append({'source_label':f'generation/{name}','source_sha256':sha256_file(p),'archive':archive.name,'sha256':sha256_file(archive)})
result={'schema_version':1,'gate':'nuisance_mapping','passed':all(r['mapping_check_passed'] for r in records),'results':records,
 'purpose':'Deterministic matched-native-model/noiseless mapping check; complementary to independent Tudat scientific experiments',
 'truth_generation':{'observation_noise_multiplier':0,'clock_noise_sigma_m':30,'ambiguities':'full integer cycles','fit_wavelength_factor':.5,'known_slips':True,'force_model':'same nominal central+J2+exponential drag native physics as inference','time_grid':'native canonical5s orbit and attitude;30s observations'},
 'fit_weights':{'code_sigma_m':.3,'phase_sigma_m':.003},
 'mapping_tolerance_m':.002,'tolerance_interpretation':'Engineering tolerance for deterministic physical-unit/preprocessing mapping, not a probabilistic uncertainty interval or a tuned scientific hyperparameter',
 'gauge_policy':'One joint global receiver-clock datum: clock minus mean clock error, IF ambiguity plus exactly the same value; no separate phase, per-track/per-satellite/trend/epoch-specific truth alignment',
 'slip_policy':'PRN and injection time checked against immediately bracketing30s retained samples; dropped/masked/never-visible segments explicitly unavailable, not counted as detections',
 'estimation_truth_inputs':False,'statistical_nuisance_uncertainty_claim':False,
 'reproduction_script':'run_nuisance_mapping.py','assessment_script':'evaluate_nuisance_recovery.py',
 'preserves_earlier_evidence':'nuisance_mapping.json',
 'earlier_evidence_sha256':sha256_file(target/'nuisance_mapping.json'),
 'source_scripts_sha256':{name:sha256_file(target/name) for name in ['run_nuisance_mapping.py','evaluate_nuisance_recovery.py']},
 'binary_sha256':sha256_file(base/'groops'),'generation_manifest_sha256':sha256_file(base/'data_manifest.json')}
write_json(target/'nuisance_mapping_74863.json',result);write_json(raw/'manifest.json',{'purpose':'Final deterministic mapping evidence, portable source labels','files':archives})
