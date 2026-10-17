"""Control fixtures for the real allowlisted validation dispatcher (no native runs)."""
from dataclasses import replace
from pathlib import Path
import json,os,sys,xml.etree.ElementTree as ET
import pytest
from orbit_poc.segmented import protocol as p,validation as v,report as r
from orbit_poc.segmented.config import SegmentedConfig,Artifact,Runtime,Resources


@pytest.fixture
def inputs(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir();root=tmp_path/'campaign';root.mkdir();data=tmp_path/'native'/'data';data.mkdir(parents=True);(data/'orbit.G01.dat').write_bytes(b'controlled original data')
    files={}
    for name in sorted(set(v.PROTECTED+v.STRUCTURAL+v.SCRIPTS+('tests/test_segmented_native_tangent.py',))):
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# controlled fixture source\n');files[name]=p.file_hash(path)
    original={};paths={}
    for role in v.original_input_hashes():
        path=tmp_path/(role+'.txt');path.write_text(role);paths[role]=path
    for role in ('density_request','pulse_request','full_day_request'):
        p.write_json(paths[role],{'estimation_inputs':[{'role':'fixture','path':str(data/'orbit.G01.dat'),'sha256':p.file_hash(data/'orbit.G01.dat')}],'output_dir':str(data.parent)})
    p.write_json(paths['flight_prepared'],{'estimation_inputs':[],'output_dir':str(data.parent)})
    for role,prefix in (('old_nuisance_replay','old'),('candidate1_nuisance_replay','new')):
        tree=ET.Element('groops')
        for tag,key in (('inputfileVariational','variational'),('inputfileNumericsReferenceParameters','reference'),('inputfileLogDensity','density')):ET.SubElement(tree,tag).text=str(paths[prefix+'_replay_'+key])
        paths[role].write_bytes(ET.tostring(tree))
    original={k:p.artifact(path) for k,path in paths.items()};expected={k:x['sha256'] for k,x in original.items()}
    monkeypatch.setattr(v,'original_input_hashes',lambda:dict(expected))
    freeze=tmp_path/'source-freeze.json';p.write_json(freeze,{'source':{'files':files}})
    reference=tmp_path/'reference.json';p.write_json(reference,{'identity':{'source_freeze_sha256':p.file_hash(freeze)}})
    from orbit_poc.segmented.multiday import native_data_inventory
    value={'schema':'orbit-poc-segmented-validation-inputs-v1','input_artifacts':original,'source_reference':p.artifact(freeze),'dependencies':[p.artifact(data/'orbit.G01.dat')],'data_directories':[native_data_inventory(data)]}
    file=tmp_path/'validation-inputs.json';p.write_json(file,value)
    config=replace(SegmentedConfig(),output_dir=str(root),validation_inputs=Artifact(**p.artifact(file)),corrected_reference=Artifact(**p.artifact(reference)))
    runtime={'source_root':str(source),'source_sha256':p.source_snapshot(source)['sha256'],'native':p.artifact(paths['prior_validation']),'python':p.artifact(sys.executable),'segmented_solver':p.artifact(paths['prior_validation']),'libraries':None}
    manifest={'validation_context_hash':'a'*64,'runtimes':{'segmented':runtime}}
    import orbit_poc.comparison.backend as old
    monkeypatch.setattr(old,'_preparation',lambda request:request)
    return config,manifest,root,source,value,file


def test_fixed_gate1_order_precedes_all_v4_checks():
    assert len(v.GATE1)==10 and len(v.STAGES)==14
    assert v.STAGES[:10]==v.GATE1
    assert v.GATE1[-2:]==('nuisance-replay','nuisance-replay-candidate1-point012')
    assert v.STAGES[10:]==('segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses')


def test_input_identity_and_protected_source_are_checked(inputs):
    config,manifest,root,source,value,file=inputs
    assert v.verify_inputs(config,manifest,source)==value
    Path(value['input_artifacts']['pulse_request']['path']).write_text('substituted easier request')
    with pytest.raises(p.NotReady):v.verify_inputs(config,manifest,source)


def test_repin_cannot_replace_an_original_input(inputs):
    config,manifest,root,source,value,file=inputs
    path=Path(value['input_artifacts']['old_nuisance_replay']['path']);path.write_text('<groops/>');value['input_artifacts']['old_nuisance_replay']=p.artifact(path);p.write_json(file,value)
    config=replace(config,validation_inputs=Artifact(**p.artifact(file)))
    with pytest.raises(ValueError,match='substituted'):v.verify_inputs(config,manifest,source)


def test_original_gate_source_cannot_change(inputs):
    config,manifest,root,source,value,file=inputs
    (source/v.PROTECTED[0]).write_text('modified test')
    with pytest.raises(ValueError,match='source changed'):v.verify_inputs(config,manifest,source)


def test_validation_native_directory_membership_is_frozen(inputs):
    config,manifest,root,source,value,file=inputs
    directory=Path(value['data_directories'][0]['root']);(directory/'orbit.G32.dat').write_text('added wildcard input')
    with pytest.raises(ValueError,match='membership'):v.verify_inputs(config,manifest,source)


def test_command_registry_rejects_arbitrary_commands_and_distinguishes_replays(inputs):
    config,manifest,root,source,value,file=inputs;runtime=manifest['runtimes']['segmented']
    with pytest.raises(ValueError,match='Unknown'):v.command('shell-injected',value,runtime,root)
    a=v.command('nuisance-replay',value,runtime,root/'old');b=v.command('nuisance-replay-candidate1-point012',value,runtime,root/'new')
    assert a[a.index('--source-profile')+1]!=b[b.index('--source-profile')+1]
    linear=v.command('linearization-pulses',value,runtime,root/'linear')
    assert linear[linear.index('--initial-state-from')+1]==value['input_artifacts']['initial_state']['path']
    assert linear[linear.index('--solver')+1]==runtime['segmented_solver']['path']


def harness_result(job,status='complete'):
    return {'status':status,'returncode':0 if status=='complete' else 1,'argv':job['argv'],'harness_execution':{'owned_process_group_cleaned':True,'runtime':job['runtime']}}


def control_mocks(monkeypatch,manifest):
    monkeypatch.setattr(p,'verify_manifest',lambda *args:manifest)
    monkeypatch.setattr(v,'execution_context',lambda *args:manifest)
    monkeypatch.setattr(p,'admission',lambda *args:None)


def test_failed_gate1_keeps_all_failures_and_blocks_gate2_without_overwrite(inputs,monkeypatch):
    config,manifest,root,source,value,file=inputs;control_mocks(monkeypatch,manifest);calls=[]
    def execute(job,*args):calls.append(job['stage']);return harness_result(job,'failed')
    monkeypatch.setattr(p,'_execute_job',execute)
    result=v.validate(config,project=source);assert result['status']=='failed' and calls==list(v.GATE1)
    first=Path(result['pipeline']);before=first.read_bytes();record=p.read_json(first)
    assert [x['status'] for x in record['steps']]==['failed']*10+['not_run']*4
    second=v.validate(config,project=source)
    assert Path(second['pipeline'])!=first and first.read_bytes()==before
    with pytest.raises(ValueError,match='not passed'):v.require_passed(config,manifest,root,source)


def test_verified_success_can_be_consumed_but_changed_command_cannot(inputs,monkeypatch):
    config,manifest,root,source,value,file=inputs;control_mocks(monkeypatch,manifest)
    monkeypatch.setattr(p,'_execute_job',lambda job,*args:harness_result(job))
    monkeypatch.setattr(v,'check_result',lambda stage,*args:{'fixture_only':stage})
    result=v.validate(config,project=source);assert result['status']=='passed'
    assert v.require_passed(config,manifest,root,source)['status']=='passed'
    request=Path(result['pipeline']).parent/'native-tests'/'request.json';record=p.read_json(request);record['validation_inputs']['sha256']='0'*64;p.write_json(request,record)
    with pytest.raises(ValueError,match='attribution'):v.require_passed(config,manifest,root,source)


def test_interruption_preserves_current_step_and_remaining_planned_inventory(inputs,monkeypatch):
    config,manifest,root,source,value,file=inputs;control_mocks(monkeypatch,manifest)
    def execute(*args):raise KeyboardInterrupt('controlled interruption before native launch')
    monkeypatch.setattr(p,'_execute_job',execute)
    result=v.validate(config,project=source);record=p.read_json(result['pipeline'])
    assert record['status']=='failed' and record['steps'][0]['status']=='interrupted_or_failed'
    assert sum(x['status']=='not_run' for x in record['steps'])==13
    assert 'KeyboardInterrupt' in record['error']


def test_run_refuses_missing_actual_prebenchmark_validation(tmp_path,monkeypatch):
    config=replace(SegmentedConfig(),output_dir=str(tmp_path));p.write_json(tmp_path/'manifest.json',{})
    monkeypatch.setattr(p,'verify_manifest',lambda *args:{})
    monkeypatch.setattr(v,'require_passed',lambda *args:(_ for _ in ()).throw(ValueError('required real gate missing')))
    called=[];monkeypatch.setattr(p,'_execute_job',lambda *args:called.append(True))
    with pytest.raises(ValueError,match='real gate'):p.run(config,project=tmp_path)
    assert not called


def test_actual_refinement_schema_and_threshold_are_parsed(tmp_path):
    source=Path(__file__).parent/'fixtures/segmented_corrected_flight_refinement.json'
    assert p.file_hash(source)=='98da6851a52c6c913f9bbe636310308593caa6b7adb58c9d06e2c6d2df75a77d'  # Exact published corrected-c24 gate bytes.
    value=p.read_json(source);root=tmp_path/'result';root.mkdir();p.write_json(root/'result.json',value)
    manifest={'runtimes':{'segmented':{'native':{'sha256':value['binary_sha256']}}}}
    assert v.check_result('flight-refinement',tmp_path,{},manifest,{})['maximum_fraction_of_sigma']<.01
    value['native_signals']['signals'][0]['maximum_fraction_of_sigma']=.01;p.write_json(root/'result.json',value)
    with pytest.raises(ValueError,match='refinement'):v.check_result('flight-refinement',tmp_path,{},manifest,{})


def test_validate_cli_is_a_real_separate_command():
    from orbit_poc.cli import parser
    args=parser().parse_args(['segmented','validate','--config','configs/segmented-v4.json'])
    assert args.segmented_command=='validate'


def test_runtime_requires_complete_library_inventory(tmp_path,monkeypatch):
    from test_segmented_protocol import runtime_fixture
    runtime,value,path=runtime_fixture(tmp_path,monkeypatch)
    with pytest.raises(p.NotReady,match='library inventory'):p.verify_runtime(replace(runtime,library_manifest=Artifact()),tmp_path)
    assert p.verify_runtime(runtime,tmp_path)['libraries']['directory']==value['directory']
    (Path(value['directory'])/'libunlisted.so').write_bytes(b'unlisted dependency')
    with pytest.raises(ValueError,match='complete directory'):p.verify_runtime(runtime,tmp_path)


def test_runtime_wheel_dlopen_inventory_is_mandatory(tmp_path,monkeypatch):
    from test_segmented_protocol import runtime_fixture
    runtime,value,path=runtime_fixture(tmp_path,monkeypatch)
    wheel=tmp_path/'python-env'/'lib'/'numpy-wheel.so';wheel.write_bytes(b'changed dynamically loaded code')
    with pytest.raises(ValueError,match='runtime tree changed'):p.verify_runtime(runtime,tmp_path)


def test_runtime_actual_dependency_closure_cannot_add_a_host_library(tmp_path,monkeypatch):
    from test_segmented_protocol import runtime_fixture
    runtime,value,path=runtime_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(p,'loader_dependencies',lambda *args:{'/unlisted/host/libc.so'})
    with pytest.raises(ValueError,match='loaded dependency'):p.verify_runtime(runtime,tmp_path)


def test_loader_ignores_only_vdso_and_clears_inherited_injection(tmp_path,monkeypatch):
    from types import SimpleNamespace
    library=tmp_path/'lib.so';library.write_bytes(b'library')
    monkeypatch.setenv('LD_PRELOAD','/untrusted/lib.so');monkeypatch.setenv('LD_AUDIT','/untrusted/audit.so');monkeypatch.setenv('LD_TRACE_LOADED_OBJECTS','2')
    seen=[]
    def run(argv,**kwargs):seen.append((argv,kwargs));return SimpleNamespace(stdout='linux-vdso.so.1 (0x01)\nlib.so => '+str(library)+' (0x02)\n')
    monkeypatch.setattr(p.subprocess,'run',run)
    assert p.loader_dependencies('pinned-loader','pinned-executable',tmp_path)=={str(library)}
    assert seen[0][0]==['pinned-loader','--list','pinned-executable'] and 'LD_PRELOAD' not in seen[0][1]['env'] and 'LD_AUDIT' not in seen[0][1]['env'] and seen[0][1]['env']['LD_TRACE_LOADED_OBJECTS']=='1'
    monkeypatch.setattr(p.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='libmissing.so => not found\n'))
    with pytest.raises(ValueError,match='Unresolved'):p.loader_dependencies('loader','binary',tmp_path)
    monkeypatch.setattr(p.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='(0x00000001)\n'))
    with pytest.raises(ValueError,match='Unresolved'):p.loader_dependencies('loader','binary',tmp_path)


def test_supervisor_cleans_tracked_detached_native_descendant(tmp_path):
    import psutil
    package=tmp_path/'source'/'src'/'orbit_poc'/'segmented';package.mkdir(parents=True);(package.parent/'__init__.py').write_text('');(package/'__init__.py').write_text('')
    (package/'backend.py').write_text("import subprocess,sys,time\nfrom pathlib import Path\ndef fit_job(job,directory):\n child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)\n Path(directory/'child.pid').write_text(str(child.pid))\n time.sleep(.2)\n raise ValueError('controlled failure with detached native child')\n")
    directory=tmp_path/'job';directory.mkdir();p.write_json(directory/'request.json',{})
    runtime={'source_root':str(package.parents[2]),'python':{'path':sys.executable},'libraries':None}
    resources=replace(Resources(),reserved_cpu_ids=(min(os.sched_getaffinity(0)),),minimum_free_output_bytes=0)
    result=p._execute_job({},directory,runtime,resources);pid=int((directory/'child.pid').read_text())
    assert result['status']=='failed' and result['harness_execution']['owned_process_group_cleaned']
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status()==psutil.STATUS_ZOMBIE


def test_actual_linearization_gate_requires_independent_original_row_qr(tmp_path):
    root=tmp_path/'result';root.mkdir();rows=root/'original-rows.npz';rows.write_bytes(b'controlled oracle artifact')
    oracle={'version':'4.2','elimination_api':'JacobianFactor.eliminate(Ordering) -> EliminateQR','rows':10,'columns':3,'maximum_equality_substitution_residual':0.,'maximum_map_discrepancy_posterior_sd':1e-10,'covariance_relative_error':1e-11,'full_residual_energy':2.,'normalized_residual_energy_difference':1e-14,'original_rows_and_result':p.artifact(rows)}
    profiles=[{'segment_seconds':seconds,'covariance_optimization_damping':0.,'covariance_all_original_coordinates':True,'covariance_relative_error':1e-11,'trials':[{'damping':damping,'maximum_map_discrepancy_posterior_sd':1e-10,'normalized_residual_energy_difference':1e-14,'normalized_orthogonal_residual_energy_difference':1e-14,'maximum_equality_backward_error':1e-14,'equality_residual_normalization':'max_i |d_i-E_i*x| / (|d_i|+sum_j |E_ij*x_j|); zero denominator gives zero'} for damping in (0.,.001,1000.)]} for seconds in (3600,14400)]
    runtime={'source_sha256':'a'*64,'native':{'sha256':'b'*64},'segmented_solver':{'sha256':'c'*64}}
    value={'schema':'orbit-poc-segmented-linearization-gate-v1','passed':True,'source_sha256':runtime['source_sha256'],'native':runtime['native'],'solver':runtime['segmented_solver'],'physical_evaluations':1,'accepted_fit_covariance':False,'map_tolerance_posterior_sd':1e-7,'relative_covariance_tolerance':1e-8,'normalized_residual_energy_tolerance':2e-12,'damping_values':[0.,.001,1000.],'comparison':{'profiles':profiles,'independent_gtsam':oracle}}
    manifest={'runtimes':{'segmented':runtime}};path=root/'validation.json';p.write_json(path,value)
    assert v.check_result('linearization-pulses',tmp_path,{},manifest,{})['maximum_map_posterior_sd']==1e-10
    oracle['maximum_map_discrepancy_posterior_sd']=1e-7;p.write_json(path,value)
    with pytest.raises(ValueError,match='GTSAM criterion'):v.check_result('linearization-pulses',tmp_path,{},manifest,{})
    del value['comparison']['independent_gtsam'];p.write_json(path,value)
    with pytest.raises(ValueError,match='GTSAM QR oracle'):v.check_result('linearization-pulses',tmp_path,{},manifest,{})


def test_validation_context_precedes_catalog_and_binds_later_manifest(inputs,monkeypatch):
    config,manifest,root,source,value,file=inputs;runtime=manifest['runtimes']['segmented']
    reference=p.read_json(config.corrected_reference.path);reference.update(scientific_correctness_gate_passed=True,native_sha256=runtime['native']['sha256']);p.write_json(config.corrected_reference.path,reference)
    config=replace(config,corrected_reference=Artifact(**p.artifact(config.corrected_reference.path)))
    monkeypatch.setattr(p,'verify_runtime',lambda *args:runtime)
    context=v.execution_context(config,root,source)
    assert not (root/'manifest.json').exists() and len(p.read_json(root/'plan.json')['attempts'])==68
    benchmark={'plan_hash':context['plan_hash'],'runtimes':context['runtimes']}
    assert v.execution_context(config,root,source,benchmark)==context
    with pytest.raises(ValueError,match='does not match'):v.execution_context(config,root,source,{**benchmark,'plan_hash':'0'*64})


def test_constraint_residual_is_separate_from_passing_energy(tmp_path):
    # Reuse the realistic result constructor above, then mutate only the native
    # equality statistic through a narrowly captured JSON write.
    original=p.write_json;captured=[]
    def capture(path,value):
        if Path(path).name=='validation.json' and not captured:captured.append(json.loads(json.dumps(value)))
        return original(path,value)
    from unittest.mock import patch
    with patch.object(p,'write_json',side_effect=capture):test_actual_linearization_gate_requires_independent_original_row_qr(tmp_path)
    value=captured[0];value['comparison']['profiles'][0]['trials'][0]['maximum_equality_backward_error']=2e-12
    original(tmp_path/'result'/'validation.json',value)
    runtime={'source_sha256':'a'*64,'native':{'sha256':'b'*64},'segmented_solver':{'sha256':'c'*64}}
    with pytest.raises(ValueError,match='True lifted equality'):v.check_result('linearization-pulses',tmp_path,{}, {'runtimes':{'segmented':runtime}}, {})


def test_uncertain_supervisor_cleanup_stops_and_blocks_next_validation(inputs,monkeypatch):
    config,manifest,root,source,value,file=inputs;control_mocks(monkeypatch,manifest);calls=[]
    def execute(job,*args):
        calls.append(job['stage']);value=harness_result(job,'failed');value['harness_execution']['owned_process_group_cleaned']=False;return value
    monkeypatch.setattr(p,'_execute_job',execute)
    result=v.validate(config,project=source);assert result['status']=='failed' and calls==['native-tests']
    with pytest.raises(p.NotReady,match='unverified owned cleanup'):v.validate(config,project=source)
    assert calls==['native-tests']


def test_supervisor_exception_is_not_reported_as_verified_cleanup(tmp_path,monkeypatch):
    from orbit_poc.segmented import supervisor
    def fail(*args,**kwargs):raise RuntimeError('controlled supervisor failure')
    monkeypatch.setattr(supervisor,'run_owned',fail)
    result=p._execute_job({},tmp_path,{'libraries':None,'source_root':str(tmp_path),'python':{'path':sys.executable}},Resources())
    assert result['status']=='failed' and not result['harness_execution']['owned_process_group_cleaned']
