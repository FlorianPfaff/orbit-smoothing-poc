"""Non-native contract tests for immutable v4 preparation/execution/reporting."""
from dataclasses import replace
from pathlib import Path
import json
import numpy as np
import pytest
from orbit_poc.segmented.config import SegmentedConfig,Artifact,config_from_dict,load_config
from orbit_poc.segmented import protocol as p,report as r


def test_exact_matrix_and_shared_families():
    cases=p.planned_cases();attempts=p.attempts(cases)
    assert len(cases)==28 and len(attempts)==68
    assert len({x['generation_id'] for x in cases if x['stage']=='synthetic'})==4
    assert sum(x['profile']=='segmented_4h' for x in attempts)==12
    assert {c['case']['seed'] for c in cases if c['stage']=='synthetic'}=={610000,610001}
    for c in cases:
        if c['stage']=='synthetic':assert (c['case']['atmosphere'],c['case']['coverage']) in (('quiet','normal'),('disturbed','blackout'))
        if c['case']['coverage']=='blackout':assert len(c['case']['mask']['intervals_seconds'])==c['case']['duration_hours']//24


def test_profile_positions_are_balanced_within_each_profile_arity():
    from collections import Counter
    cases=p.planned_cases();attempts=p.attempts(cases)
    positions={2:[Counter() for _ in range(2)],3:[Counter() for _ in range(3)]}
    visited=[]
    for case in cases:
        rows=[row for row in attempts if row['case_id']==case['case_id']]
        expected=p.PROFILES if case['case']['duration_hours']==24 else p.PROFILES[:2]
        assert {row['profile'] for row in rows}==set(expected)
        visited.extend(rows)
        for index,row in enumerate(rows):positions[len(rows)][index][row['profile']]+=1
    assert visited==attempts  # Original case order remains unchanged.
    assert [row['order'] for row in attempts]==list(range(68))
    assert positions[3]==[Counter({profile:4 for profile in p.PROFILES}) for _ in range(3)]
    assert positions[2]==[Counter({profile:8 for profile in p.PROFILES[:2]}) for _ in range(2)]


def test_profile_positions_are_balanced_within_each_duration():
    from collections import Counter
    cases=p.planned_cases();attempts=p.attempts(cases)
    for hours in (24,48,72):
        profiles=p.PROFILES if hours==24 else p.PROFILES[:2]
        counts=[Counter() for _ in profiles]
        selected=[case for case in cases if case['case']['duration_hours']==hours]
        assert len(selected)==(12 if hours==24 else 8)
        for case in selected:
            rows=[row for row in attempts if row['case_id']==case['case_id']]
            for index,row in enumerate(rows):counts[index][row['profile']]+=1
        assert counts==[Counter({profile:4 for profile in profiles}) for _ in profiles]


def test_profile_order_balances_duration_method_coverage_and_regime_margins():
    from collections import Counter
    cases=p.planned_cases();attempts=p.attempts(cases)
    for hours in (24,48,72):
        profiles=p.PROFILES if hours==24 else p.PROFILES[:2]
        selected=[case for case in cases if case['case']['duration_hours']==hours]
        categories={'method':lambda c:c['method'],'coverage':lambda c:c['case']['coverage'],
                    'regime':lambda c:'flight' if c['stage']=='flight' else c['case']['orbit']}
        for category,key in categories.items():
            for value in {key(case) for case in selected}:
                group=[case for case in selected if key(case)==value]
                positions=[Counter() for _ in profiles]
                for case in group:
                    rows=[row for row in attempts if row['case_id']==case['case_id']]
                    for index,row in enumerate(rows):positions[index][row['profile']]+=1
                for position in positions:
                    counts=[position[profile] for profile in profiles]
                    if len(group)%len(profiles)==0:
                        assert counts==[len(group)//len(profiles)]*len(profiles)
                    else:
                        assert category=='regime' and hours==24
                        assert max(counts)-min(counts)<=1


def test_same_family_reverses_paired_order_between48_and72_hours():
    cases=p.planned_cases();attempts=p.attempts(cases)
    for family in {case['family_id'] for case in cases if case['stage']=='synthetic'}:
        rows={case['case']['duration_hours']:[x['profile'] for x in attempts if x['case_id']==case['case_id']]
              for case in cases if case['family_id']==family}
        assert rows[48]==list(reversed(rows[72]))


def test_profile_order_is_repeatable_and_does_not_mutate_cases():
    cases=p.planned_cases();before=json.loads(json.dumps(cases))
    first=p.attempts(cases)
    assert first==p.attempts(cases)==p.attempts()==p.attempts(json.loads(json.dumps(cases)))
    assert cases==before


@pytest.mark.parametrize('change',[{'unknown':1},{'controls':{'maximum_accepted_iterations':33}},{'resources':{'threads':2}},{'resources':{'maximum_process_tree_rss_bytes':1}},{'profiles':['dense_corrected']},{'schema_version':True},{'preparation':{'generate_missing':'yes'}},{'dense_runtime':{'native':{'path':'/x','sha256':''}}}])
def test_configuration_rejects_unfrozen_options(change):
    with pytest.raises(ValueError):config_from_dict(change)


def test_duplicate_json_keys(tmp_path):
    path=tmp_path/'c.json';path.write_text('{"name":"a","name":"b"}')
    with pytest.raises(ValueError,match='Duplicate'):load_config(path)


def test_seed_scan_and_repin_collision(tmp_path):
    path=tmp_path/'old.json';p.write_json(path,{'nested':[{'seeds':[510000,510001]}]})
    config=replace(SegmentedConfig(),prior_seed_protocols=(Artifact(**p.artifact(path)),))
    assert p.seed_inventory(config,tmp_path)['overlap']==[]
    p.write_json(path,{'nested':{'seed':610000}})
    with pytest.raises(p.NotReady):p.seed_inventory(config,tmp_path)
    config=replace(config,prior_seed_protocols=(Artifact(**p.artifact(path)),))
    with pytest.raises(ValueError,match='already'):p.seed_inventory(config,tmp_path)


def test_missing_runtime_still_freezes_all68_and_reports(tmp_path):
    project=tmp_path/'source';project.mkdir();(project/'pyproject.toml').write_text('')
    config=SegmentedConfig(output_dir=str(tmp_path/'out'))
    prepared=p.prepare(config,project=project)
    assert prepared['status']=='blocked'
    summary=r.create_report(config,project=project)
    report=p.read_json(summary['report'])
    assert len(report['attempts'])==68 and report['status_counts']=={'not_run':68}
    assert report['release_ready'] is False and report['gates']['original150_completion']['status']=='pending_or_failed'
    assert '68' in Path(summary['html']).read_text()


def test_plan_rejects_source_and_config_changes(tmp_path):
    project=tmp_path/'source';(project/'src').mkdir(parents=True);file=project/'src'/'a.py';file.write_text('v=1')
    root=tmp_path/'out';root.mkdir();config=SegmentedConfig()
    p.freeze_plan(config,root,project);file.write_text('v=2')
    with pytest.raises(ValueError):p.freeze_plan(config,root,project)


def test_checkpoint_preserves_failure_and_rejects_wrong_job(tmp_path):
    job={'job_sha256':'1'*64};result={'status':'timeout','job_sha256':'1'*64,'converged':False}
    p.write_json(tmp_path/'request.json',job);p.write_json(tmp_path/'result.json',result)
    p.write_json(tmp_path/'result-record.json',{'job_sha256':'1'*64,'status':'timeout','result':p.artifact(tmp_path/'result.json')})
    assert p.checkpoint(tmp_path,job)['status']=='timeout'
    with pytest.raises(ValueError):p.checkpoint(tmp_path,{'job_sha256':'2'*64})
    p.write_json(tmp_path/'result.json',{**result,'status':'complete'})
    with pytest.raises(p.NotReady):p.checkpoint(tmp_path,job)


def test_request_rejects_truth_before_native_import():
    c=p.planned_cases()[0]
    with pytest.raises(ValueError,match='Reference'):p._verify_request({**c,'truth':'secret'},c)


def test_strict_check_does_not_accept_small_damped_step(monkeypatch):
    import orbit_poc.numerics.protocol as old
    monkeypatch.setattr(old,'validate_complete_result',lambda *args:True)
    result={'strict_nuisance_converged':True,'strict_final_correction':{'fresh_undamped':True,'maximum_position_change_m':1e-6,'normalized_scaled_gradient':1e-10,'maximum_pulse_update_m_s':1e-10}}
    assert r.strict_result(result,{'method':'groops_pulses'})
    result['strict_final_correction']['fresh_undamped']=False
    with pytest.raises(ValueError):r.strict_result(result,{'method':'groops_pulses'})


def estimate(tmp_path,name,delta=0,noise_delta=0):
    path=tmp_path/(name+'.npz');np.savez(path,mjd=[60000.,60000.1],states=np.zeros((2,6)),covariance=np.tile(np.eye(6)*(1+delta),(2,1,1)),prediction_mjd=[60000.,60000.1],prediction_covariance=np.tile(np.eye(6),(2,1,1)))
    pred=tmp_path/(name+'-pred.npz');np.savez(pred,row_ids=['a','b'],values_m=np.array([1,2.])+noise_delta,sigma_m=[.3,.003])
    physical=tmp_path/(name+'-physical.json');p.write_json(physical,{'force':[.1,.2],'force_units':'log density'})
    cross=tmp_path/(name+'-cross.npz');np.savez(cross,indices=[[0,1]],mjd=[[60000.,60000.1]],covariance=np.eye(12)[None,:,:])
    dynamic=tmp_path/(name+'-dynamic.npz');np.savez(dynamic,force_indices=[0,1],covariance=np.eye(8))
    return {'preprocessing_audit_sha256':'1'*64,'objective':2.,'objective_resolution':1e-10,'artifacts':[{'role':role,**p.artifact(file)} for role,file in [('state_estimate',path),('segmented_predictions',pred),('physical_parameters',physical),('cross_segment_covariance',cross),('selected_dynamic_covariance',dynamic)]]}


def test_equivalence_uses_noise_and_covariance_not_fit_status(tmp_path):
    dense=estimate(tmp_path,'a');good=estimate(tmp_path,'b',delta=1e-9,noise_delta=1e-7)
    assert r.equivalence(dense,good)['status']=='passed'
    bad=estimate(tmp_path,'c',noise_delta=4e-5)
    assert r.equivalence(dense,bad)['status']=='failed'
    bad=estimate(tmp_path,'d',delta=1e-5)
    assert r.equivalence(dense,bad)['status']=='failed'
    good['objective']+=1e-5
    assert r.equivalence(dense,good)['status']=='failed'


def test_external_gates_require_runtime_and_manifest_identity(tmp_path):
    file=tmp_path/'g.json';p.write_json(file,{'schema':'orbit-poc-segmented-gates-v1','manifest_hash':'wrong'})
    config=replace(SegmentedConfig(),release_evidence=Artifact(**p.artifact(file)))
    with pytest.raises(ValueError,match='bound'):r.external_gates(config,{'manifest_hash':'right'},tmp_path)


def test_original150_rejects_an_incomplete_report(tmp_path):
    manifest={'attempts':[]};manifest['manifest_hash']=p.canonical_hash(manifest)
    m=tmp_path/'m.json';report=tmp_path/'report.json';p.write_json(m,manifest);p.write_json(report,{'manifest_hash':manifest['manifest_hash'],'expected_attempts':150,'terminal_attempts':149,'execution_complete':False})
    config=replace(SegmentedConfig(),original150_manifest=Artifact(**p.artifact(m)),original150_report=Artifact(**p.artifact(report)))
    with pytest.raises(ValueError,match='incomplete'):r.original_benchmark(config,tmp_path)


def test_cli_dispatch_is_separate():
    from orbit_poc.cli import parser
    args=parser().parse_args(['segmented','run','--config','configs/segmented-v4.json','--max-attempts','1'])
    assert args.command=='segmented' and args.segmented_command=='run' and args.max_attempts==1


@pytest.fixture
def frozen_inputs(tmp_path,monkeypatch):
    project=tmp_path/'source';(project/'src').mkdir(parents=True);(project/'src'/'sentinel.py').write_text('value=1\n')
    root=tmp_path/'run';inputs=tmp_path/'inputs';inputs.mkdir()
    native=inputs/'native';native.write_text('executable placeholder for injected unit executor')
    runtime={'source_root':str(project),'source_sha256':p.source_snapshot(project)['sha256'],'native':p.artifact(native),'python':p.artifact(native),'build_manifest':p.artifact(native),'libraries':None,'segmented_solver':p.artifact(native)}
    monkeypatch.setattr(p,'verify_runtime',lambda *args:runtime)
    prior=inputs/'prior.json';p.write_json(prior,{'seeds':[510000,510001]})
    ref=inputs/'reference.json';p.write_json(ref,{'scientific_correctness_gate_passed':True,'native_sha256':runtime['native']['sha256']})
    monkeypatch.setattr(p,'flight_sources',lambda *args:{c['case_id']:{} for c in p.planned_cases() if c['stage']=='flight'})
    monkeypatch.setattr(p,'verify_flight_request',lambda *args:None)
    records=[]
    for role in ('gnss_observations','gnss_orbits','gnss_clocks','bootstrap_orbit','attitude','spacecraft_metadata','earth_orientation'):
        path=inputs/(role+'.txt');path.write_text(role);records.append({'role':role,**p.artifact(path),**({'provenance':'gnss_only'} if role=='bootstrap_orbit' else {})})
    from orbit_poc.segmented.multiday import native_data_inventory
    native_data=inputs/'native-prepared'/'data';native_data.mkdir(parents=True);(native_data/'orbit.G01.dat').write_bytes(b'fixture native input')
    directory_inventory=native_data_inventory(native_data)
    entries=[]
    for i,c in enumerate(p.planned_cases()):
        identity={k:('1'*64 if k!='mask_hash' else p.canonical_hash(c['case']['mask'])) for k in p.IDENTITIES}
        prep={**identity,'output_dir':str(native_data.parent),'native_data_inventory':directory_inventory,'duration_hours':c['case']['duration_hours'],'native_artifacts':records,'multiday_preparation':{'generation_id':c['generation_id'],'continuous_source_hours':72,'prefix_hours':c['case']['duration_hours'],'mask_before_initialization':True}}
        path=inputs/(str(i)+'-prepared.json');p.write_json(path,prep)
        request={**{k:c[k] for k in ('stage','method','case','parameters')},**identity,'estimation_inputs':[ *records,{'role':'force_auxiliary','metadata':{'kind':'native_preparation'},**p.artifact(path)}]}
        target=inputs/(str(i)+'-request.json');p.write_json(target,request);entries.append({'case_id':c['case_id'],'request':p.artifact(target)})
    catalog=inputs/'catalog.json';p.write_json(catalog,{'schema':'orbit-poc-segmented-input-catalog-v1','entries':entries})
    config=replace(SegmentedConfig(),output_dir=str(root),corrected_reference=Artifact(**p.artifact(ref)),prior_seed_protocols=(Artifact(**p.artifact(prior)),),prepared_input_catalog=Artifact(**p.artifact(catalog)))
    return config,project,root,records


def test_prepare_freezes_real_input_bytes_and_run_resumes_only_matching_terminal(frozen_inputs,monkeypatch):
    config,project,root,_=frozen_inputs
    assert p.prepare(config,project=project)['status']=='prepared'
    from orbit_poc.segmented import validation
    monkeypatch.setattr(validation,'require_passed',lambda *args: {'status':'fixture-only-not-a-scientific-result'})
    calls=[];monkeypatch.setattr(p,'admission',lambda *args:None)
    def execute(job,*args):calls.append(job);return {'status':'timeout','converged':False,'covariance_valid':False,'error':'injected deadline'}
    monkeypatch.setattr(p,'_execute_job',execute)
    result=p.run(config,project=project,max_attempts=1);assert result['terminal_attempts']==1
    result=p.run(config,project=project,max_attempts=1);assert result['terminal_attempts']==2 and len(calls)==2
    summary=r.create_report(config,project=project);report=p.read_json(summary['report'])
    assert len(report['attempts'])==68 and report['status_counts']=={'timeout':2,'not_run':66} and not report['release_ready']
    third=p.attempts()[2];directory=root/'attempts'/third['attempt_id'];directory.mkdir();(directory/'worker.log').write_text('interrupted')
    with pytest.raises(p.NotReady,match='Interrupted'):p.run(config,project=project,max_attempts=1)


def test_frozen_input_mutation_blocks_resume(frozen_inputs):
    config,project,root,records=frozen_inputs
    assert p.prepare(config,project=project)['status']=='prepared'
    Path(records[0]['path']).write_text('changed observations')
    with pytest.raises(ValueError,match='modified'):p.verify_manifest(config,root,project)
    summary=r.create_report(config,project=project)
    assert p.read_json(summary['report'])['release_ready'] is False


def test_nested_daily_product_mutation_is_detected(tmp_path):
    file=tmp_path/'daily.gz';file.write_bytes(b'provider product')
    value={'daily_sources':[p.artifact(file)]};p.verify_nested_artifacts(value)
    file.write_bytes(b'changed provider product')
    with pytest.raises(p.NotReady):p.verify_nested_artifacts(value)


def runtime_fixture(tmp_path,monkeypatch):
    """Real file inventories; only external ELF loader output is substituted."""
    from orbit_poc.segmented.config import Runtime
    from orbit_poc.segmented.multiday import native_data_inventory
    src=tmp_path/'source';src.mkdir(exist_ok=True)
    prefix=tmp_path/'native-env';lib=prefix/'lib';lib.mkdir(parents=True)
    library=lib/'libfixture.so';library.write_bytes(b'controlled dependency')
    loader=lib/'ld-fixture.so';loader.write_bytes(b'controlled loader')
    native=prefix/'bin'/'groops';native.parent.mkdir();native.write_text('#!/bin/sh\nexit 0\n');native.chmod(0o755)
    python=tmp_path/'python-env'/'bin'/'python';python.parent.mkdir(parents=True);python.write_text('#!/bin/sh\nexit 0\n');python.chmod(0o755)
    wheel=python.parent.parent/'lib'/'numpy-wheel.so';wheel.parent.mkdir();wheel.write_bytes(b'dlopen fixture')
    build=tmp_path/'build.json';p.write_json(build,{'schema_version':1,'executable_sha256':p.file_hash(native),'mpi':False})
    trees={}
    for role,directory in (('python_environment',python.parent.parent),('native_environment',prefix)):
        path=tmp_path/(role+'.json');p.write_json(path,native_data_inventory(directory));trees[role]=p.artifact(path)
    manifest=tmp_path/'libraries.json'
    value={'schema':'orbit-poc-segmented-runtime-closure-v1','directory':str(lib),'files':[p.artifact(library),p.artifact(loader)],'loader':p.artifact(loader),'runtime_trees':trees,'executables':{role:{'executable':p.artifact(exe),'dependencies':[p.artifact(library),p.artifact(loader)]} for role,exe in (('native',native),('python',python))}}
    p.write_json(manifest,value)
    monkeypatch.setattr(p,'loader_dependencies',lambda *args:{str(library.resolve()),str(loader.resolve())})
    runtime=Runtime(source_root=str(src),source_sha256=p.source_snapshot(src)['sha256'],python=Artifact(**p.artifact(python)),native=Artifact(**p.artifact(native)),build_manifest=Artifact(**p.artifact(build)),library_manifest=Artifact(**p.artifact(manifest)))
    return runtime,value,manifest


def test_actual_build_manifest_schema(tmp_path,monkeypatch):
    runtime,_,_=runtime_fixture(tmp_path,monkeypatch)
    assert p.verify_runtime(runtime,tmp_path)['native']['sha256']==runtime.native.sha256


def test_real_worker_failure_is_preserved_and_group_cleanup_verified(tmp_path,monkeypatch):
    import os,sys
    from orbit_poc.segmented.config import Resources
    source=tmp_path/'source';package=source/'src'/'orbit_poc'/'segmented';package.mkdir(parents=True)
    (package.parent/'__init__.py').write_text('');(package/'__init__.py').write_text('')
    (package/'backend.py').write_text("def fit_job(job,directory):\n raise ValueError('intentional controlled worker failure')\n")
    directory=tmp_path/'job';directory.mkdir();p.write_json(directory/'request.json',{})
    runtime={'source_root':str(source),'python':{'path':sys.executable},'libraries':None}
    resources=replace(Resources(),reserved_cpu_ids=(min(os.sched_getaffinity(0)),),minimum_free_output_bytes=0)
    result=p._execute_job({},directory,runtime,resources)
    assert result['status']=='failed' and result['harness_execution']['owned_process_group_cleaned']
    assert 'intentional controlled worker failure' in (directory/'worker.log').read_text()


def release_fixture():
    cases={c['case_id']:c for c in p.planned_cases()}
    rows=[{**a,**{k:cases[a['case_id']][k] for k in ('stage','method','case')},'status':'complete','strict_success':True} for a in p.attempts()]
    pairs=[{'dense_attempt':x['case_id']+'--dense_corrected','segmented_attempt':x['attempt_id'],'regression':False,'status':'passed'} for x in rows if x['profile']!='dense_corrected']
    gates={k:{'status':'passed'} for k in ('native_correctness','original150_completion')}
    return rows,pairs,gates


def test_release_allows_long_dense_timeout_without_substitution():
    rows,pairs,gates=release_fixture();assert all(r.release_conditions(rows,pairs,gates).values())
    dense=next(x for x in rows if x['profile']=='dense_corrected' and x['case']['duration_hours']==72)
    dense.update(status='timeout',strict_success=False)
    for pair in pairs:
        if pair['dense_attempt']==dense['attempt_id']:pair['status']='unavailable'
    assert all(r.release_conditions(rows,pairs,gates).values())
    required=next(x for x in rows if x['profile']=='segmented_1h' and x['case'].get('orbit')=='leo500' and x['case'].get('atmosphere')=='disturbed' and x['case']['duration_hours']==72)
    required.update(status='failed',strict_success=False)
    assert not r.release_conditions(rows,pairs,gates)['required72h_both_methods_strict']


def test_release_blocks_dense_success_segmented_failure_and_missing_flight():
    rows,pairs,gates=release_fixture();pairs[0]['regression']=True
    assert not r.release_conditions(rows,pairs,gates)['no_dense_success_segmented_failure']
    pairs[-1]['status']='unavailable'
    assert not r.release_conditions(rows,pairs,gates)['flight_equivalence']
    gates['original150_completion']['status']='pending_or_failed'
    assert not r.release_conditions(rows,pairs,gates)['all_external_gates']


def test_added_native_glob_file_invalidates_frozen_preparation(frozen_inputs):
    config,project,root,records=frozen_inputs
    assert p.prepare(config,project=project)['status']=='prepared'
    data=Path(records[0]['path']).parent/'native-prepared'/'data'
    (data/'orbit.G32.dat').write_bytes(b'new wildcard-visible transmitter')
    with pytest.raises(ValueError,match='membership'):p.verify_manifest(config,root,project)


def gate_fixture(tmp_path,name,manifest,*,junit=None,measurement=None):
    identity={'check':name,'manifest_hash':manifest['manifest_hash'],'native_sha256':manifest['runtimes']['segmented']['native']['sha256'],'source_sha256':manifest['runtimes']['segmented']['source_sha256']}
    folder=tmp_path/name;folder.mkdir(parents=True)
    invocation=folder/'invocation.json';p.write_json(invocation,{**identity,'schema':'orbit-poc-segmented-gate-invocation-v1','returncode':0,'status':'completed','timed_out':False,'cleanup_verified':True,'argv':['fixture-only-no-native-run']})
    result=folder/('result.xml' if junit else 'result.json')
    if junit:result.write_text(junit)
    else:
        raw=folder/'raw.txt';raw.write_text('controlled test measurement')
        p.write_json(result,{**identity,'schema':'orbit-poc-segmented-measured-gate-v1','status':'passed','raw_artifacts':[p.artifact(raw)],**measurement})
    receipt={**identity,'schema':'orbit-poc-segmented-gate-receipt-v1','status':'passed','invocation':p.artifact(invocation),'result':p.artifact(result)}
    if junit:
        import xml.etree.ElementTree as ET
        inventory=folder/'inventory.json';p.write_json(inventory,[{'classname':x.get('classname',''),'name':x.get('name','')} for x in ET.fromstring(junit).findall('.//testcase')]);receipt['test_inventory']=p.artifact(inventory)
    path=folder/'receipt.json';p.write_json(path,receipt);return {'evidence':p.artifact(path)}


def test_gate_evidence_does_not_accept_failed_junit_or_unrelated_receipt(tmp_path):
    manifest={'manifest_hash':'a'*64,'runtimes':{'segmented':{'source_sha256':'b'*64,'native':{'sha256':'c'*64}}}}
    item=gate_fixture(tmp_path,'original_native_tests',manifest,junit='<testsuites><testsuite><testcase name="one"><failure/></testcase></testsuite></testsuites>')
    with pytest.raises(ValueError,match='failed/skipped'):r._gate_result(item,'original_native_tests',manifest,tmp_path)
    path=Path(item['evidence']['path']);receipt=p.read_json(path);receipt['source_sha256']='d'*64;p.write_json(path,receipt);item={'evidence':p.artifact(path)}
    with pytest.raises(ValueError,match='identity'):r._gate_result(item,'original_native_tests',manifest,tmp_path)


def test_measured_gate_values_are_read_from_bound_result(tmp_path):
    manifest={'manifest_hash':'a'*64,'runtimes':{'segmented':{'source_sha256':'b'*64,'native':{'sha256':'c'*64}}}}
    item=gate_fixture(tmp_path,'maximum_lift_true_residual',manifest,measurement={'value':3e-12})
    item['value']=0.
    assert r._gate_result(item,'maximum_lift_true_residual',manifest,tmp_path)['value']==3e-12


def test_post_execution_reporting_attachments_do_not_change_manifest(frozen_inputs):
    config,project,root,_=frozen_inputs
    assert p.prepare(config,project=project)['status']=='prepared'
    manifest=p.verify_manifest(config,root,project);before=manifest['manifest_hash'];r.create_report(config,project=project)
    evidence=root/'actual-gate-evidence.json';p.write_json(evidence,{'schema':'orbit-poc-segmented-gates-v1','manifest_hash':before,'native_sha256':manifest['runtimes']['segmented']['native']['sha256'],'source_sha256':manifest['runtimes']['segmented']['source_sha256']})
    attached=replace(config,release_evidence=Artifact(**p.artifact(evidence)))
    assert p.verify_manifest(attached,root,project)['manifest_hash']==before
    r.create_report(attached,project=project)
    attachments=list((root/'reporting-inputs').glob('*.json'));assert len(attachments)==2
    assert all(p.read_json(x)['manifest_hash']==before for x in attachments)


def original150_fixture(tmp_path):
    from orbit_poc.numerics.config import NumericsConfig
    from orbit_poc.numerics.protocol import attempt_job
    from dataclasses import asdict
    profiles=('legacy_v3','qr_lm_legacy_jacobian','qr_lm_staged_jacobian')
    attempts=[{'attempt_id':f'c{i}--{profile}','case_id':f'c{i}','profile':profile,'order':i*3+j} for i in range(50) for j,profile in enumerate(profiles)]
    cfg=NumericsConfig();plan={'config':asdict(cfg),'attempts':attempts};plan['plan_hash']=p.canonical_hash(plan)
    runtime={'native':{'path':'/fixture/original-groops','sha256':'1'*64},'source_sha256':'2'*64}
    cases=[{'case_id':f'c{i}','fit_request':{'method':'groops_pulses'},'input_manifest_hash':p.canonical_hash(i)} for i in range(50)]
    manifest={'plan_hash':plan['plan_hash'],'cases':cases,'attempts':attempts,'legacy_runtime':runtime,'new_runtime':runtime};manifest['manifest_hash']=p.canonical_hash(manifest)
    rows=[]
    for a in attempts:
        c=cases[int(a['case_id'][1:])];job=attempt_job(cfg,manifest,c,a);directory=tmp_path/a['attempt_id'];directory.mkdir()
        p.write_json(directory/'request.json',job)
        result={'status':'failed','request_hash':p.canonical_hash(job),'input_manifest_hash':c['input_manifest_hash'],'numerics_profile':a['profile'],'numerics_manifest_hash':manifest['manifest_hash'],'harness_execution':{'runtime':runtime}}
        p.write_json(directory/'result.json',result);rows.append({**a,'status':'failed','result':p.artifact(directory/'result.json')})
    report={'plan_hash':plan['plan_hash'],'manifest_hash':manifest['manifest_hash'],'expected_attempts':150,'terminal_attempts':150,'execution_complete':True,'attempts':rows}
    for name,value in (('plan',plan),('manifest',manifest),('report',report)):p.write_json(tmp_path/(name+'.json'),value)
    return replace(SegmentedConfig(),original150_plan=Artifact(**p.artifact(tmp_path/'plan.json')),original150_manifest=Artifact(**p.artifact(tmp_path/'manifest.json')),original150_report=Artifact(**p.artifact(tmp_path/'report.json')))


def test_original150_each_result_must_match_its_actual_attempt(tmp_path):
    config=original150_fixture(tmp_path)
    assert r.original_benchmark(config,tmp_path)['status']=='passed'
    path=tmp_path/'report.json';report=p.read_json(path)
    for i,row in enumerate(report['attempts']):row['result']=report['attempts'][i%3]['result']
    p.write_json(path,report);bad=replace(config,original150_report=Artifact(**p.artifact(path)))
    with pytest.raises(ValueError,match='per-attempt'):r.original_benchmark(bad,tmp_path)


def test_actual_shaped_objective_artifact_requires_original_inequalities(tmp_path):
    # Published validation bytes provide the real schema; this is a parser test,
    # never a new scientific run or new-source gate result.
    source=Path(__file__).parent/'fixtures/segmented_corrected_density_objective.json'
    assert p.file_hash(source)=='47cc44fded1eda6d629385c95785d96821cc0660c007b53c833be4c792228ec4'  # Exact published corrected-c24 gate bytes.
    value=p.read_json(source);path=tmp_path/'validation.json';p.write_json(path,value)
    manifest={'runtimes':{'segmented':{'native':{'sha256':value['native_binary_sha256']}}}}
    assert r.objective_validation(p.artifact(path),'groops_log_drag_ou',manifest,tmp_path)==[.125,.0625]
    value['directional_derivatives'][-1]['positive_cost']+=10;p.write_json(path,value)
    with pytest.raises(ValueError,match='allowance|arithmetic'):r.objective_validation(p.artifact(path),'groops_log_drag_ou',manifest,tmp_path)


def test_native_directory_inventory_includes_link_targets(tmp_path):
    from orbit_poc.segmented.multiday import native_data_inventory
    target=tmp_path/'cache';target.mkdir();(target/'clock.G01.dat').write_text('clock')
    data=tmp_path/'data';data.mkdir();(data/'clock').symlink_to(target,target_is_directory=True)
    before=native_data_inventory(data)
    other=tmp_path/'other';other.mkdir();(other/'clock.G01.dat').write_text('clock')
    (data/'clock').unlink();(data/'clock').symlink_to(other,target_is_directory=True)
    assert native_data_inventory(data)!=before


def test_equivalence_requires_physical_and_cross_covariance_agreement(tmp_path):
    dense=estimate(tmp_path,'dense');other=estimate(tmp_path,'other')
    physical=next(x for x in other['artifacts'] if x['role']=='physical_parameters');p.write_json(physical['path'],{'force':[.1002,.2],'force_units':'log density'});physical.update(p.artifact(physical['path']))
    assert r.equivalence(dense,other)['status']=='failed'
    other=estimate(tmp_path,'cross');item=next(x for x in other['artifacts'] if x['role']=='cross_segment_covariance')
    cov=np.eye(12);cov[:6,6:]=np.eye(6)*1e-5;cov[6:,:6]=np.eye(6)*1e-5
    np.savez(item['path'],indices=[[0,1]],mjd=[[60000.,60000.1]],covariance=cov[None,:,:]);item.update(p.artifact(item['path']))
    assert r.equivalence(dense,other)['status']=='failed'
    other['artifacts']=[x for x in other['artifacts'] if x['role']!='cross_segment_covariance']
    with pytest.raises(ValueError,match='missing'):r.equivalence(dense,other)


def test_nominal_observation_covariance_must_agree(tmp_path):
    dense=estimate(tmp_path,'dense');other=estimate(tmp_path,'other')
    item=next(x for x in other['artifacts'] if x['role']=='state_estimate')
    with np.load(item['path']) as z:arrays={k:z[k] for k in z.files}
    arrays['prediction_covariance']*=1.001;np.savez(item['path'],**arrays);item.update(p.artifact(item['path']))
    assert r.equivalence(dense,other)['status']=='failed'
    arrays['prediction_mjd']+=.001;np.savez(item['path'],**arrays);item.update(p.artifact(item['path']))
    with pytest.raises(ValueError,match='epochs'):r.equivalence(dense,other)


def test_same_count_substituted_test_inventory_is_rejected(tmp_path):
    import xml.etree.ElementTree as ET
    manifest={'manifest_hash':'a'*64,'runtimes':{'segmented':{'source_sha256':'b'*64,'native':{'sha256':'c'*64}}}}
    inventory=r.fixed_test_inventory('original_native_tests');root=ET.Element('testsuites');suite=ET.SubElement(root,'testsuite')
    for item in inventory:ET.SubElement(suite,'testcase',item)
    item=gate_fixture(tmp_path/'good','original_native_tests',manifest,junit=ET.tostring(root,encoding='unicode'))
    assert r._gate_result(item,'original_native_tests',manifest,tmp_path)['passed']==106
    suite[0].set('name','substituted_same_count')
    item=gate_fixture(tmp_path/'bad','original_native_tests',manifest,junit=ET.tostring(root,encoding='unicode'))
    with pytest.raises(ValueError,match='substituted'):r._gate_result(item,'original_native_tests',manifest,tmp_path)


def test_passing_replay_wrapper_cannot_override_failed_native_receipt(tmp_path):
    reference=Path(__file__).parent/'fixtures/segmented_corrected_replay_receipt.json'
    assert p.file_hash(reference)=='a384e30ec5c56ca338a86d555a048e175973f191c48a52bba8050114969ca9ac'  # Exact published corrected-c24 native receipt.
    value=p.read_json(reference);value['passed']=False;path=tmp_path/'receipt.json';p.write_json(path,value)
    row={'receipt':p.artifact(path),'status':'strict_converged','floor_limited':False,'raw_update_m':0.}
    manifest={'runtimes':{'segmented':{'native':{'sha256':value['native_sha256']}}}}
    with pytest.raises(ValueError,match='Actual original replay'):r.replay_validation(row,{},manifest,tmp_path)


def test_actual_replay_receipt_is_bound_to_source_and_physical_xml(tmp_path):
    import xml.etree.ElementTree as ET
    reference=Path(__file__).parent/'fixtures/segmented_corrected_replay_receipt.json'
    assert p.file_hash(reference)=='a384e30ec5c56ca338a86d555a048e175973f191c48a52bba8050114969ca9ac'  # Exact published corrected-c24 native receipt.
    value=p.read_json(reference);tree=ET.Element('groops');inputs={}
    for tag,key in (('inputfileVariational','variational'),('inputfileNumericsReferenceParameters','reference'),('inputfileLogDensity','density')):
        path=tmp_path/key;path.write_text(key);inputs[key]=p.artifact(path);ET.SubElement(tree,tag).text=str(path)
    source=tmp_path/'source.xml';source.write_bytes(ET.tostring(tree));executed=tmp_path/'executed.xml';executed.write_bytes(source.read_bytes())
    value['source_profile_sha256']=p.file_hash(source);value['replay_profile_sha256']=p.file_hash(executed)
    path=tmp_path/'receipt.json';p.write_json(path,value)
    provenance={'source_profile_sha256':p.file_hash(source),'physical_input_hashes':{k:v['sha256'] for k,v in inputs.items()},'original_and_executed_xml_inputs_match':True}
    row={'receipt':p.artifact(path),'source_profile':p.artifact(source),'executed_profile':p.artifact(executed),'physical_inputs':inputs,'provenance':provenance,'status':'strict_converged','floor_limited':False,'raw_update_m':value['profile']['maximum_update_m']}
    manifest={'runtimes':{'segmented':{'native':{'sha256':value['native_sha256']}}}}
    assert r.replay_validation(row,{'provenance':provenance},manifest,tmp_path)==value['profile']['maximum_update_m']
    tree[0].text='/substituted/variational';executed.write_bytes(ET.tostring(tree));row['executed_profile']=p.artifact(executed);value['replay_profile_sha256']=p.file_hash(executed);p.write_json(path,value);row['receipt']=p.artifact(path)
    with pytest.raises(ValueError,match='physical input'):r.replay_validation(row,{'provenance':provenance},manifest,tmp_path)


def test_native_preprocessing_identity_must_match_across_profiles(tmp_path):
    dense=estimate(tmp_path,'dense');other=estimate(tmp_path,'other')
    other['preprocessing_audit_sha256']='2'*64
    with pytest.raises(ValueError,match='support/weights'):r.equivalence(dense,other)

@pytest.fixture
def original_flight(tmp_path):
    from orbit_poc.segmented.multiday import native_data_inventory
    rows=[]
    for role in ('gnss_observations','gnss_orbits','gnss_clocks','bootstrap_orbit','attitude','spacecraft_metadata','earth_orientation'):
        path=tmp_path/(role+'.dat');path.write_bytes(role.encode());rows.append({'role':role,**p.artifact(path),**({'provenance':'gnss_only'} if role=='bootstrap_orbit' else {})})
    native=tmp_path/'original-native'/'data';native.mkdir(parents=True);(native/'G01.dat').write_bytes(b'original transmitter')
    plan_cases=[];manifest_cases=[]
    for case in (c for c in p.planned_cases() if c['stage']=='flight'):
        name='retained-april24-'+case['case']['coverage']+'-'+case['method']
        identities={k:('a'*64 if k!='mask_hash' else p.canonical_hash(case['case']['mask'])) for k in p.IDENTITIES}
        prepared={**identities,'duration_hours':24.,'output_dir':str(native.parent),'native_artifacts':rows}
        prep=tmp_path/(name+'-prepared.json');p.write_json(prep,prepared)
        request={**{k:case[k] for k in ('stage','case','method','parameters')},**identities,'estimation_inputs':[*rows,{'role':'force_auxiliary','metadata':{'kind':'native_preparation'},**p.artifact(prep)}]}
        historical=tmp_path/(name+'-historical.json');p.write_json(historical,{**request,'historical_only':'retained result context'})
        planned={'case_id':name,'origin':'retained_flight_control',**{k:case[k] for k in ('stage','case','method','parameters')},'historical_request':p.artifact(historical)}
        plan_cases.append(planned);manifest_cases.append({**planned,'fit_request':request,'lineage':{'request':p.artifact(historical)}})
    for i in range(46):plan_cases.append({'case_id':'other-'+str(i)});manifest_cases.append({'case_id':'other-'+str(i)})
    attempts=[{'attempt_id':'original-'+str(i)} for i in range(150)]
    plan={'cases':plan_cases,'attempts':attempts};plan['plan_hash']=p.canonical_hash(plan);planpath=tmp_path/'original-plan.json';p.write_json(planpath,plan)
    manifest={'cases':manifest_cases,'attempts':attempts,'plan_hash':plan['plan_hash']};manifest['manifest_hash']=p.canonical_hash(manifest);manifestpath=tmp_path/'original-manifest.json';p.write_json(manifestpath,manifest)
    catalog=tmp_path/'flight-catalog.json';p.write_json(catalog,{'schema':'orbit-poc-segmented-flight-inputs-v1','original_plan':p.artifact(planpath),'original_manifest':p.artifact(manifestpath)})
    return replace(SegmentedConfig(),flight_input_catalog=Artifact(**p.artifact(catalog))),tmp_path,native


def test_original_april24_requests_are_wrapped_without_repreparation(original_flight):
    config,root,native=original_flight;original=p.flight_sources(config,root)
    assert len(original)==4
    for key,value in original.items():
        request=p.wrap_flight_request(value,root/'wrappers'/key);p.verify_flight_request(request,value)
        case=next(c for c in p.planned_cases() if c['case_id']==key);p._verify_request(request,case)
        if request['method']=='groops_log_drag_ou':assert request['parameters']['tau_seconds']==7200 and request['parameters']['sigma_log_density']==.3
        assert 'duration_seconds' not in request['case']['mask']
        assert request['estimation_inputs'][:-1]==value['request']['estimation_inputs'][:-1]


def test_fresh_flight_substitution_is_rejected_even_when_new_hashes_are_valid(original_flight):
    config,root,native=original_flight;value=next(iter(p.flight_sources(config,root).values()));request=p.wrap_flight_request(value,root/'wrapper')
    new=root/'fresh-observations.dat';new.write_bytes(b'new downloaded or regenerated observation set')
    changed={**request,'estimation_inputs':[{**x,**p.artifact(new)} if x['role']=='gnss_observations' else x for x in request['estimation_inputs']]}
    with pytest.raises(ValueError,match='exact original'):p.verify_flight_request(changed,value)
    request['parameters']={**request['parameters'],'tau_seconds':1800.}
    with pytest.raises(ValueError,match='exact original'):p.verify_flight_request(request,value)


def test_original_flight_wrapper_cannot_replace_prepared_trajectory(original_flight):
    config,root,native=original_flight;value=next(iter(p.flight_sources(config,root).values()));request=p.wrap_flight_request(value,root/'wrapper')
    prep=request['estimation_inputs'][-1];record=p.read_json(prep['path']);record['native_paths']={'orbit':'a new fit'};p.write_json(prep['path'],record)
    request['estimation_inputs'][-1]={**prep,**p.artifact(prep['path'])}
    with pytest.raises(ValueError,match='original preparation'):p.verify_flight_request(request,value)


def test_original_flight_directory_addition_invalidates_wrapped_request(original_flight):
    config,root,native=original_flight;key,value=next(iter(p.flight_sources(config,root).items()));request=p.wrap_flight_request(value,root/'wrapper')
    (native/'G32.dat').write_bytes(b'new wildcard-visible transmitter')
    with pytest.raises(ValueError,match='membership'):p._verify_request(request,next(c for c in p.planned_cases() if c['case_id']==key))


def test_flight_normalization_compares_full_ledger_after_exact_bias_verification(tmp_path):
    requests=[]
    for i in range(2):
        folder=tmp_path/str(i);folder.mkdir();bias=folder/'bias.gz';bias.write_bytes(b'exact original bias bytes')
        ledger=folder/'normalization.json';p.write_json(ledger,{'schema_version':1,'bias_inputs':[p.artifact(bias)],'formula':'unchanged physical formula','corrections':[{'signal':'C1C','delta_m':.123}],'arc':{'day':'2024-04-24'},'policies':{'apply':True}})
        requests.append({'stage':'flight',**{key:'a'*64 for key in p.IDENTITIES},'estimation_inputs':[{'role':'force_auxiliary','metadata':{'kind':'known_gnss_osb_datum_normalization'},**p.artifact(ledger)}]})
    assert requests[0]['estimation_inputs'][0]['sha256']!=requests[1]['estimation_inputs'][0]['sha256']
    assert p.shared_input_identity(requests[0])==p.shared_input_identity(requests[1])
    ledger=Path(requests[1]['estimation_inputs'][0]['path']);value=p.read_json(ledger);value['corrections'][0]['delta_m']=.124;p.write_json(ledger,value);requests[1]['estimation_inputs'][0].update(p.artifact(ledger))
    assert p.shared_input_identity(requests[0])!=p.shared_input_identity(requests[1])
    Path(value['bias_inputs'][0]['path']).write_bytes(b'changed bias underneath old receipt')
    with pytest.raises(p.NotReady):p.shared_input_identity(requests[1])
