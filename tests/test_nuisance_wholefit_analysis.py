"""Whole-fit outcomes preserve censoring and require independent strict evidence."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys

import numpy as np
import pytest

BASE = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('wholefit_analysis', BASE/'scripts/analyze_nuisance_wholefit.py')
check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
spec = importlib.util.spec_from_file_location('small_pair_fixtures', BASE/'tests/test_nuisance_performance_pair.py')
small = importlib.util.module_from_spec(spec); spec.loader.exec_module(small)


def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True))
    return path


def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def pin(path): return {'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size}


def fixture(tmp_path, *, statuses=('timeout','timeout')):
    root = tmp_path/'experiment'; root.mkdir()
    source = root/'source'; helper=source/'src/orbit_poc/segmented/supervisor.py'
    shutil.copytree(BASE/'src/orbit_poc',source/'src/orbit_poc',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    inputs = root/'inputs';inputs.mkdir()
    controls = {}
    controls['python']=pin(Path(sys.executable).resolve())
    for name in ('worker','runner','native'):
        path = inputs/name;path.write_text('pinned '+name);controls[name]=pin(path)
    job = {'method':'groops_pulses','segmented_profile':'dense_corrected','numerics_profile':'qr_lm_staged_jacobian',
           'backend':{'groops_executable':controls['native']['path']},'expected_native_binary_sha256':controls['native']['sha256'],
           'force_model_hash':'a'*64,'measurement_model_hash':'b'*64,'preprocessing_hash':'c'*64,'mask_hash':'d'*64,
           'source_hash':'e'*64,'numerical_controls':dict(check.LIMITS)}
    requests={}
    for cache in (0,1):
        value={**job,'nuisance_performance_cache':cache,'id':'nuisance-wholefit-cache'+str(cache)+'--fixture'}
        value['job_sha256']=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        requests[cache]=write(inputs/('request'+str(cache)+'.json'),value)
    freeze={'schema':'orbit-poc-nuisance-wholefit-freeze-v1','root':str(root),'source_root':str(source),
        'source_hash':'e'*64,'cpu':0,'host':'fixture','boot_id':'fixture-boot','wall_time_seconds':7200,
        'maximum_process_tree_rss_bytes':8*1024**3,'minimum_free_output_bytes':100,
        'jobs':[{'name':'cache'+str(i),'cache':i,'request':pin(requests[i]),'job_sha256':read(requests[i])['job_sha256']} for i in (1,0)],
        'pinned_files':[*[pin(p) for p in sorted((source/'src').rglob('*.py'))],*[pin(r) for r in requests.values()],*controls.values()],
        'python':controls['python'],'worker':controls['worker'],'runner':controls['runner'],
        'environment':{k:'1' for k in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS',
                                     'NUMEXPR_NUM_THREADS','ORBIT_POC_NUISANCE_PERFORMANCE']}}
    freeze_path=write(root/'freeze.json',freeze)
    for cache,status in enumerate(statuses):
        request=requests[cache]
        run=root/('cache'+str(cache));run.mkdir();(run/'request.json').write_bytes(request.read_bytes())
        argv=[freeze['python']['path'],'-s','-B',freeze['worker']['path'],str(source),str(run/'request.json'),
              str(run/'worker-result.json'),str(cache),str(freeze_path),sha(freeze_path)]
        plan=write(run/'supervisor.plan.json',{'argv':argv,'helper_sha256':sha(helper),'boot_id':freeze['boot_id'],
            'timeout_seconds':7200,'max_process_tree_rss_bytes':8*1024**3,'min_free_disk_bytes':100,
            'cwd':str(source),'working_directory':str(run)})
        outer='complete' if status in ('complete','failed') else status
        supervisor=write(run/'supervisor.json',{'schema':'orbit-poc-segmented-supervision-v1','argv':argv,
            'status':outer,'returncode':0 if outer=='complete' else -15,'owned_process_group_cleaned':True,
            'cleanup':{'verified':True},'helper_sha256':sha(helper),'boot_id':freeze['boot_id'],
            'plan_sha256':sha(plan),'worker':{'pid':10+cache},'elapsed_seconds':7200 if outer=='timeout' else 50.,
            'peak_process_tree_rss_bytes':10000})
        write(run/'effective-environment.json',{'schema':'orbit-poc-nuisance-wholefit-environment-v1',
            'cache':cache,'environment':{**freeze['environment'],'ORBIT_POC_NUISANCE_INTERPOLATION_CACHE':str(cache)},
            'cpu_affinity':[0],'freeze_sha256':sha(freeze_path),'request_sha256':sha(request),
            'source':str(source),'boot_id':freeze['boot_id'],'pid':10+cache})
        worker={'status':status,'converged':False,'covariance_valid':False}
        if outer=='complete': write(run/'worker-result.json',worker)
        result={**worker,'freeze_sha256':sha(freeze_path),'cache':cache,'request_sha256':sha(request),
                'harness_execution':read(supervisor),'evidence':{}}
        write(run/'result.json',result); refresh(run)
        write(run/'post-input-check.json',{'verified':True,'freeze_sha256':sha(freeze_path),
                                         'pinned_file_count':len(freeze['pinned_files'])})
    return root


def refresh(run):
    result=read(run/'result.json')
    for key,name in [('request','request.json'),('supervisor','supervisor.json'),('worker_result','worker-result.json'),
                     ('effective_environment','effective-environment.json')]:
        path=run/name; result['evidence'][key]=pin(path) if path.exists() else None
    result['harness_execution']=read(run/'supervisor.json')
    write(run/'result.json',result)


def mutate(run, name, key, value):
    path=run/name;data=read(path);data[key]=value;write(path,data);refresh(run)


def add_points(root, tmp_path, label='point-001-initial'):
    temp=tmp_path/('small-'+label);temp.mkdir()
    off,on=small.pair(temp)
    for cache,old in enumerate((off,on)):
        run=root/('cache'+str(cache));point=run/label;shutil.copytree(old,point)
        for name in ['physical_initial.txt','fixed_force.txt','full_pulses_um_s.txt']:(point/name).write_text('same numerical inputs\n')
        write(point/'closure.json',{'converged':True,'tighter':False,'iterations':[{'position_change_m':1e-9}]})
        ex=read(point/'profile.execution.json');ex['command']=[read(run/'request.json')['backend']['groops_executable'],str(point/'profile.xml')]
        ex['native_binary_sha256']=read(run/'request.json')['expected_native_binary_sha256'];ex['elapsed_seconds']=5.
        write(point/'profile.execution.json',ex)
        for f in point.glob('qr.*.factor.json'):
            value=read(f);value['spool_directory']=str(run/'row-spool');write(f,value)
    return root/'cache0'/label,root/'cache1'/label


def success_pair(tmp_path):
    root=fixture(tmp_path,statuses=('complete','complete'))
    point_pairs=[add_points(root,tmp_path,label) for label in [
        'point-001-initial','point-002-repeat','point-003-closure-refinement',
        'point-004-confirmation','point-005-final-covariance']]
    off,on=point_pairs[-1]
    for cache,point in enumerate((off,on)):
        run=point.parent; job=read(run/'request.json')
        for f in run.glob('point-*/qr.*.rows.tsv'):
            original=pin(f);packed=f.with_name(f.name+'.gz');packed.write_bytes(gzip.compress(f.read_bytes(),mtime=0))
            write(f.with_name(f.name+'.compression.json'),{'round_trip_verified':True,'source':original,'compressed':pin(packed)})
            f.unlink()
        np.savez_compressed(run/'fit.npz',times=np.array([0.,30.]),mjd=np.array([60000.,60001.]),states=np.zeros((2,6)),
            covariance=np.tile(np.eye(6),(2,1,1)),prediction_mjd=np.array([60000.,60001.]),prediction_covariance=np.tile(np.eye(6),(2,1,1)))
        write(run/'physical_parameters.json',{'initial_state_si':[0.]*6,'force':[0.],'force_units':'um/s','objective':2.})
        np.savez_compressed(run/'cross.npz',indices=np.array([[0,1]]),mjd=np.array([[60000.,60001.]]),covariance=np.eye(12)[None])
        np.savez_compressed(run/'dynamic.npz',force_indices=np.array([0]),covariance=np.eye(7))
        np.savez_compressed(run/'predictions.npz',row_ids=np.array(['a','b']),sigma_m=np.array([.3,.003]),values_m=np.array([0.,0.]))
        mapping={'state_estimate':run/'fit.npz','physical_parameters':run/'physical_parameters.json',
          'cross_segment_covariance':run/'cross.npz','selected_dynamic_covariance':run/'dynamic.npz',
          'segmented_predictions':run/'predictions.npz','native_nuisance_profile':point/'qr.profile.json',
          'native_fit_configuration':point/'profile.xml','native_qr_factor':point/'qr.3.R.bin',
          'native_qr_rhs':point/'qr.3.rhs.bin','native_qr_coordinates':point/'qr.3.factor.json',
          'native_qr_diagnostics':point/'qr.3.diagnostics.json','native_objective':point/'qr.3.profile.json',
          'native_qr_parameters':point/'qr.3.parameters.tsv','native_qr_row_provenance':point/'qr.3.rows.tsv.gz',
          'native_qr_row_compression_receipt':point/'qr.3.rows.tsv.compression.json'}
        for role in check.SUCCESS_ROLES-set(mapping):
            path=run/(role+'.txt');path.write_text('identical output\n');mapping[role]=path
        result={**job,'status':'complete','numerical_status':'complete','converged':True,'covariance_valid':True,
          'covariance_scope':'marginalized','parameter_blocks':['initial_state','pulses','float_ambiguities'],
          'preprocessing_audit_sha256':sha(mapping['native_preprocessing_audit']),
          'native_binary_sha256':job['expected_native_binary_sha256'],'metadata':{'reference_inputs_used':False},
          'numerical_diagnostics':{},'strict_nuisance_converged':True,
          'strict_final_correction':{'fresh_undamped':True,'maximum_position_change_m':1e-6,
              'maximum_pulse_update_m_s':1e-10,'maximum_density_update':0.,'normalized_scaled_gradient':1e-10},
          'objective':2.,'objective_resolution':1e-10,
          'accepted_iterations':0,'trial_evaluations':0,'objective_floor':1e-10,
          'history':[{'confirmation':True,'accepted':True,'objective':2.,'normalized_gradient':1e-10}],
          'confirmation_checks':[{'stationary':True,'nuisance_floor_limited':False,
                                  'physical_parameters_unchanged':True}],
          'artifacts':[{'role':role,**pin(path)} for role,path in sorted(mapping.items())]}
        result['runtime']={'execution':[read(p[cache]/'profile.execution.json') for p in point_pairs]}
        result['numerical_diagnostics']=result['runtime']
        write(run/'native_runtime.json',result['runtime'])
        write(run/'worker-result.json',result)
        write(run/'iterations.json',{**{k:result[k] for k in ['status','converged','accepted_iterations',
            'trial_evaluations','objective_floor','history','confirmation_checks']},'elapsed_seconds':50.+cache})
        wrapper=read(run/'result.json');wrapper={**result,**{k:wrapper[k] for k in ['freeze_sha256','cache','request_sha256','harness_execution','evidence']}}
        write(run/'result.json',wrapper);refresh(run)
    return root


def rewrite_worker(run, value):
    write(run/'worker-result.json',value)
    old=read(run/'result.json');new={**value,**{k:old[k] for k in ['freeze_sha256','cache','request_sha256','harness_execution','evidence']}}
    write(run/'result.json',new);refresh(run)


def test_two_timeouts_are_valid_outcomes_not_equivalence(tmp_path):
    result=check.analyze(fixture(tmp_path))
    assert result['analysis_status']=='valid',result['issues']
    assert [r['outcome'] for r in result['runs']]==['timeout','timeout']
    assert result['scientific_equivalence']['status']=='not_evaluable'
    assert result['whole_fit_complete_pair'] is False
    assert all(not r['accepted_covariance'] for r in result['runs'])
    assert result['outcome_comparison']['whole_fit_time_ratio'] is None


@pytest.mark.parametrize('status',['failed','memory_limit','disk_limit','interrupted'])
def test_each_failure_or_limit_is_retained(tmp_path,status):
    result=check.analyze(fixture(tmp_path,statuses=(status,'timeout')))
    assert result['analysis_status']=='valid',result['issues']
    assert next(r for r in result['runs'] if r['cache']==0)['outcome']==status


def test_unstarted_second_case_remains_planned(tmp_path):
    root=fixture(tmp_path);shutil.rmtree(root/'cache0')
    result=check.analyze(root)
    assert result['analysis_status']=='pending'
    assert len(result['runs'])==2
    assert result['runs'][1]['outcome']=='not_started'


def test_running_case_is_not_read_as_closed(tmp_path):
    root=fixture(tmp_path);(root/'cache0/result.json').unlink()
    write(root/'cache0/point-001-initial/qr.profile.json',{'invalid':'growing file'})
    result=check.analyze(root)
    assert result['analysis_status']=='pending'
    assert not result['runs'][1]['points']


@pytest.mark.parametrize('name,key,value',[
    ('supervisor.json','status','running'),('supervisor.json','owned_process_group_cleaned',False),
    ('supervisor.json','helper_sha256','0'*64),('supervisor.json','plan_sha256','0'*64),
    ('supervisor.json','boot_id','wrong'),('effective-environment.json','cache',0),
    ('effective-environment.json','cpu_affinity',[1]),('effective-environment.json','pid',999),
    ('post-input-check.json','verified',False)])
def test_corrupt_control_or_treatment_fails(tmp_path,name,key,value):
    root=fixture(tmp_path);mutate(root/'cache1',name,key,value)
    result=check.analyze(root)
    assert result['analysis_status']=='invalid'
    assert result['whole_fit_complete_pair'] is False


def test_input_change_is_not_hidden_by_timeout(tmp_path):
    root=fixture(tmp_path);(root/'inputs/native').write_text('mutated binary')
    result=check.analyze(root)
    assert result['analysis_status']=='invalid' and 'identity mismatch' in str(result['issues'])


def test_request_mismatch_fails(tmp_path):
    root=fixture(tmp_path);mutate(root/'cache0','request.json','mask_hash','1'*64)
    assert check.analyze(root)['analysis_status']=='invalid'


def test_timeout_cannot_claim_completed_covariance(tmp_path):
    root=fixture(tmp_path);mutate(root/'cache1','result.json','covariance_valid',True)
    assert check.analyze(root)['analysis_status']=='invalid'


def test_complete_process_with_failed_numerics_stays_failed(tmp_path):
    root=fixture(tmp_path,statuses=('failed','failed'))
    result=check.analyze(root)
    assert result['analysis_status']=='valid'
    assert all(r['outcome']=='failed' for r in result['runs'])


def test_completed_matching_partial_points_compare_without_wholefit_claim(tmp_path):
    root=fixture(tmp_path);add_points(root,tmp_path)
    result=check.analyze(root)
    assert result['analysis_status']=='valid',result['issues']
    assert result['partial_point_comparisons'][0]['status']=='equal_completed_point'
    assert result['scientific_equivalence']['status']=='not_evaluable'


def test_scientific_change_in_common_point_is_exposed(tmp_path):
    root=fixture(tmp_path);_,on=add_points(root,tmp_path)
    value=read(on/'qr.1.profile.json');value['direct_cost']+=1e-12;write(on/'qr.1.profile.json',value)
    result=check.analyze(root)
    assert result['analysis_status']=='valid'
    assert result['scientific_equivalence']['status']=='failed_available_prefix'


def test_spool_normalization_is_exact_and_scoped(tmp_path):
    root=fixture(tmp_path);off,on=add_points(root,tmp_path)
    value=read(on/'qr.1.factor.json');value['spool_directory']=str(on.parent/'other-spool');write(on/'qr.1.factor.json',value)
    result=check.analyze(root)
    assert result['analysis_status']=='invalid' and 'spool' in str(result['issues'])


def test_matching_labels_do_not_imply_matching_physical_states(tmp_path):
    root=fixture(tmp_path);_,on=add_points(root,tmp_path);(on/'fixed_force.txt').write_text('different state\n')
    result=check.analyze(root)
    assert result['partial_point_comparisons'][0]['status']=='physical_inputs_differ_or_incomplete'


def test_declared_native_retention_preserves_hash_comparisons(tmp_path):
    root=fixture(tmp_path);off,on=add_points(root,tmp_path)
    for point in (off,on):
        artifacts=[]
        for name in ['qr.1.R.bin','qr.1.rhs.bin']:
            path=point/name;artifacts.append(pin(path));path.unlink()
        write(point/'qr.1.retention.json',{'schema':'orbit-poc-native-factor-retention-v1','status':'completed','artifacts':artifacts})
    result=check.analyze(root)
    assert result['analysis_status']=='valid',result['issues']
    comparisons=result['partial_point_comparisons'][0]['scientific_comparisons']
    assert any(c['scope']=='recorded pre-release identity' for c in comparisons)


def test_missing_completed_artifacts_cannot_disappear_on_both_sides(tmp_path):
    root=fixture(tmp_path);off,on=add_points(root,tmp_path)
    for point in (off,on):(point/'qr.1.parameters.tsv').unlink()
    assert check.analyze(root)['analysis_status']=='invalid'


def test_strict_complete_pair_requires_and_compares_real_artifacts(tmp_path):
    result=check.analyze(success_pair(tmp_path))
    assert result['analysis_status']=='valid',result['issues']
    assert result['whole_fit_complete_pair'] is True
    assert result['scientific_equivalence']['status']=='passed',result['scientific_equivalence']
    assert all(r['accepted_covariance'] for r in result['runs'])
    assert result['release_authority'] is False


@pytest.mark.parametrize('key,value',[
    ('strict_nuisance_converged',False),('covariance_valid',False),('converged',False),
    ('objective',2.1),('objective_resolution',None),('preprocessing_hash','bad')])
def test_complete_flags_cannot_replace_strict_evidence(tmp_path,key,value):
    root=success_pair(tmp_path);run=root/'cache1';worker=read(run/'worker-result.json');worker[key]=value;rewrite_worker(run,worker)
    result=check.analyze(root)
    assert result['analysis_status']=='invalid',result


def test_relaxed_final_correction_rejected(tmp_path):
    root=success_pair(tmp_path);run=root/'cache1';worker=read(run/'worker-result.json')
    worker['strict_final_correction']['maximum_position_change_m']=3e-5;rewrite_worker(run,worker)
    assert check.analyze(root)['analysis_status']=='invalid'


def test_missing_final_covariance_never_passes(tmp_path):
    root=success_pair(tmp_path);(root/'cache1/fit.npz').unlink()
    assert check.analyze(root)['analysis_status']=='invalid'


def test_npz_wrapper_does_not_relax_scientific_values(tmp_path):
    root=success_pair(tmp_path);run=root/'cache1';path=run/'fit.npz'
    with np.load(path) as z:values={k:z[k] for k in z.files}
    values['states'][0,0]=1e-12;np.savez_compressed(path,**values)
    worker=read(run/'worker-result.json')
    for item in worker['artifacts']:
        if item['role']=='state_estimate':item.update(pin(path))
    rewrite_worker(run,worker)
    result=check.analyze(root)
    assert result['analysis_status']=='valid',result['issues']
    assert result['scientific_equivalence']['status']=='failed'
    assert 'state_estimate' in result['scientific_equivalence']['exact_result_differences']


def test_stable_evidence_detects_edit_after_read(tmp_path):
    p=tmp_path/'file';p.write_text('before');ledger=check.Evidence();ledger.fingerprint(p);p.write_text('after')
    with pytest.raises(ValueError,match='changed'):ledger.unchanged()


def test_strict_json_rejects_duplicate_key_and_nonfinite(tmp_path):
    for text in ['{"status":"timeout","status":"complete"}','{"value":NaN}']:
        path=tmp_path/'receipt.json';path.write_text(text)
        with pytest.raises(ValueError):check.Evidence().json(path)


def test_timeout_partial_json_remains_explicit_unknown(tmp_path):
    root=fixture(tmp_path);point=root/'cache1/point-001-initial';point.mkdir()
    (point/'qr.1.profile.json').write_text('{"direct_cost":')
    (point/'closure.json').write_text('{"converged":')
    result=check.analyze(root)
    assert result['analysis_status']=='valid',result['issues']
    info=result['runs'][0]['points'][point.name]
    assert len(info['incomplete_records'])==2
    assert info['profile_elapsed_seconds'] is None
    assert result['scientific_equivalence']['status']=='not_evaluable'


def test_corrupt_completed_profile_cannot_hide_as_timeout_partial(tmp_path):
    root=fixture(tmp_path);_,on=add_points(root,tmp_path)
    (on/'qr.1.profile.json').write_text('{"direct_cost":')
    result=check.analyze(root)
    assert result['analysis_status']=='invalid'


def test_controller_strict_rejection_is_preserved_as_failed_outcome(tmp_path):
    root=fixture(tmp_path,statuses=('failed','failed'));run=root/'cache1'
    write(run/'worker-result.json',{'status':'complete','converged':True,'covariance_valid':True})
    result=read(run/'result.json');result.update(reported_worker_status='complete',
        error='Complete worker receipt failed the existing strict gate: required artifacts missing')
    write(run/'result.json',result);refresh(run)
    report=check.analyze(root)
    assert report['analysis_status']=='valid',report['issues']
    assert report['runs'][0]['outcome']=='failed' and not report['runs'][0]['accepted_covariance']


def test_invalid_fullfit_limits_fail_before_execution_status(tmp_path):
    root=fixture(tmp_path);freeze=read(root/'freeze.json');freeze['wall_time_seconds']=7201;write(root/'freeze.json',freeze)
    assert check.analyze(root)['analysis_status']=='invalid'


def test_unfrozen_environment_field_fails(tmp_path):
    root=fixture(tmp_path);run=root/'cache1';env=read(run/'effective-environment.json')
    env['environment']['ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE']='1';write(run/'effective-environment.json',env);refresh(run)
    assert check.analyze(root)['analysis_status']=='invalid'


def test_child_cache_setting_is_checked(tmp_path):
    root=fixture(tmp_path);_,on=add_points(root,tmp_path);path=on/'qr.1.nuisance_performance.json';value=read(path)
    value['ordinary_trials'][0]['row_build']['interpolation_cache']=False;write(path,value)
    result=check.analyze(root)
    assert result['analysis_status']=='invalid' and 'Child native cache' in str(result['issues'])


def test_fullfit_optimizer_path_is_exact_science(tmp_path):
    root=success_pair(tmp_path);run=root/'cache1';value=read(run/'iterations.json')
    value['history']=[{'accepted':False,'reason':'different decision'}];write(run/'iterations.json',value)
    result=check.analyze(root)
    assert result['analysis_status']=='invalid',result['issues']
    assert 'Optimizer record is stale' in str(result['issues'])


def test_completed_run_missing_recorded_native_cache_hits_fails(tmp_path):
    root=success_pair(tmp_path);run=root/'cache1'
    for path in run.glob('point-*/qr.*.nuisance_performance.json'):
        value=read(path)
        for row in [value['parent_row_build'],value['zero_update_replay']['row_build'],value['ordinary_trials'][0]['row_build']]:
            row['interpolation_cache_hits']=0;row['interpolation_evaluations']=row['interpolation_calls']
        write(path,value)
    assert check.analyze(root)['analysis_status']=='invalid'


def test_identically_stale_optimizer_records_cannot_pass(tmp_path):
    root=success_pair(tmp_path)
    for cache in (0,1):
        path=root/('cache'+str(cache))/'iterations.json';value=read(path)
        value.update(status='failed',converged=False);write(path,value)
    assert check.analyze(root)['analysis_status']=='invalid'


@pytest.mark.parametrize('caches',[(1,),(0,1)])
def test_missing_completed_point_is_not_harmless_progress(tmp_path,caches):
    root=success_pair(tmp_path)
    for cache in caches:shutil.rmtree(root/('cache'+str(cache))/'point-002-repeat')
    report=check.analyze(root)
    assert report['analysis_status']=='invalid',report
    assert report['scientific_equivalence']['status']!='passed'


def test_scientific_gate_loader_ignores_and_restores_mutable_module(tmp_path,monkeypatch):
    import types
    root=success_pair(tmp_path)
    fake=types.ModuleType('orbit_poc.segmented.report')
    fake.strict_result=lambda *args: (_ for _ in ()).throw(AssertionError('mutable gate called'))
    monkeypatch.setitem(sys.modules,'orbit_poc.segmented.report',fake)
    report=check.analyze(root)
    assert report['analysis_status']=='valid',report['issues']
    assert report['scientific_equivalence']['status']=='passed'
    assert sys.modules['orbit_poc.segmented.report'] is fake
    assert any(item['path'].endswith('/source/src/orbit_poc/segmented/report.py') for item in report['evidence'])


def test_frozen_scientific_gate_edit_is_rejected(tmp_path):
    root=success_pair(tmp_path)
    path=root/'source/src/orbit_poc/segmented/report.py';path.write_text('raise AssertionError("replaced")\n')
    report=check.analyze(root)
    assert report['analysis_status']=='invalid'
    assert 'identity mismatch' in str(report['issues'])


def test_cache_off_child_cannot_report_hits(tmp_path):
    root=fixture(tmp_path);off,_=add_points(root,tmp_path)
    path=off/'qr.1.nuisance_performance.json';value=read(path)
    row=value['ordinary_trials'][0]['row_build']
    row['interpolation_cache_hits']=1;row['interpolation_evaluations']=row['interpolation_calls']-1
    write(path,value)
    report=check.analyze(root)
    assert report['analysis_status']=='invalid'
    assert 'Cache-off child reports cache hits' in str(report['issues'])


def test_complete_optimizer_difference_remains_exact_science(tmp_path):
    root=success_pair(tmp_path);run=root/'cache1';worker=read(run/'worker-result.json')
    worker['history'][0]['normalized_gradient']=2e-10
    rewrite_worker(run,worker)
    value=read(run/'iterations.json');value['history']=worker['history'];write(run/'iterations.json',value)
    report=check.analyze(root)
    assert report['analysis_status']=='valid',report['issues']
    assert report['scientific_equivalence']['status']=='failed'
    assert 'optimizer_record' in report['scientific_equivalence']['exact_result_differences']


@pytest.mark.parametrize('cache',[0,1])
def test_complete_fit_requires_positive_supervised_wall(tmp_path,cache):
    root=success_pair(tmp_path);run=root/('cache'+str(cache))
    mutate(run,'supervisor.json','elapsed_seconds',0.)
    report=check.analyze(root)
    assert report['analysis_status']=='invalid'
    assert 'nonpositive supervised wall time' in str(report['issues'])
    assert not report['whole_fit_complete_pair']


def test_nonfinite_wall_ratio_is_reported_as_invalid(tmp_path):
    root=success_pair(tmp_path);mutate(root/'cache1','supervisor.json','elapsed_seconds',1e-320)
    report=check.analyze(root)
    assert report['analysis_status']=='invalid'
    assert 'wall ratio is not finite' in str(report['issues'])
    assert not report['whole_fit_complete_pair']
    json.dumps(report,allow_nan=False)
