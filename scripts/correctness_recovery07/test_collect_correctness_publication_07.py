"""Fabricated fixtures only: no candidate source, native executable or campaign."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest
from recovery_fixture_07 import install

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('publication_collector',HERE/'collect_correctness_publication_07.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)


def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(c.encoded(data))


@pytest.fixture
def bundle(tmp_path):
    root=tmp_path/'correctness';control=root/'control';run=root/'validation-07'
    previous=root/'previous';report=root/'report-02';audit=run/'independent-audit.json'
    control.mkdir(parents=True)
    shutil.copyfile(HERE/'render_correctness_report_07.py',control/'render_correctness_report_07.py')
    manifest=root/'binaries-04/groops-fixture.build-manifest.json'
    write(manifest,{'executable_sha256':'b'*64,'extension':{'files':{'stagedVariationalBody.h':'c'*64}}})
    native={'path':str(root/'binaries-04/groops-fixture'),'sha256':'b'*64,'build_manifest_sha256':c.sha(manifest.read_bytes())}
    build={'name':'build','status':'passed','returncode':0,'elapsed_seconds':42.}
    prior={'status':'failed','native':native,'source':{'sha256':'a'*64},'final_cleanup':{'verified':True},
        'resume':{'status':'resumed'},'error':'pytest capture failed before execution','steps':[build]}
    write(root/'validation-01/pipeline.json',prior)
    for suffix in ('01','02','03'):
        pause=control/('pause-'+suffix+'.json');write(pause,{'status':'paused','checkpoints':['failed','timeout']})
        write(control/('resume-'+suffix+'.json'),{'status':'resumed','pause_receipt':{'path':str(pause),'sha256':c.sha(pause.read_bytes())}})
    write(control/'candidate-inputs.json',{'source_tree_sha256':'a'*64,'inputs':[{'path':'/home/private/person/data.bin','sha256':'d'*64}]})
    write(control/'candidate02-validation-review.json',{'status':'automated_checks_passed'})
    write(control/'live-campaign-spec.json',{'scope':'frozen campaign, no altered fits'})
    second={**prior,'reused_build':{'prior_pipeline':{'path':str(root/'validation-01/pipeline.json'),'sha256':c.sha((root/'validation-01/pipeline.json').read_bytes())},
        'native':native,'source_sha256':prior['source']['sha256'],'build_step':build}}
    write(root/'validation-02/pipeline.json',second)
    controls={}
    for filename,key in (('validate_candidate_03.py','driver_sha256'),('with_correctness_namespace_03.py','wrapper_sha256'),
                         ('boundary_pause.py','boundary_sha256'),('live-campaign-spec.json','spec_sha256')):
        path=control/filename
        if not path.exists():path.write_text('# mock control')
        controls[key]=c.sha(path.read_bytes())
    pins={'source_sha256':'a'*64,**controls}
    write(control/'candidate03-pins.json',pins)
    write(control/'candidate03-control-validation.json',{'passed':True})
    write(control/'candidate03-independent-control-review.json',{'passed':True})
    pipeline={'status':'failed','finished_at':'2026-10-15T00:00:00Z','final_cleanup':{'verified':True},
        'resume':json.loads((control/'resume-03.json').read_text()),'source':{'sha256':'a'*64},'native':native,'steps':[build],
        'helper_sha256':controls['driver_sha256'],'wrapper':{'sha256':controls['wrapper_sha256']},
        'required_pins':{'path':str(control/'candidate03-pins.json'),'sha256':c.sha((control/'candidate03-pins.json').read_bytes())},
        'pause_receipt':{'path':str(control/'pause-03.json'),'sha256':c.sha((control/'pause-03.json').read_bytes())},
        'prior_failed_validation':{'path':str(root/'validation-02/pipeline.json'),'sha256':c.sha((root/'validation-02/pipeline.json').read_bytes())}}
    pipeline,_=install(root,pipeline)
    (run/'native-tests.xml').write_text('<testsuites><testsuite tests="2" failures="1" errors="0" skipped="0"><testcase name="ok"/><testcase name="failure"><failure message="roundoff">at /home/private/person/check.py</failure><system-out>PRIVATE LOG CONTENT</system-out></testcase></testsuite></testsuites>')
    for method in c.METHODS:
        data={'passed':False,'error':'original criterion failed','native_binary_sha256':'b'*64,
            'relative_derivative_tolerance':1e-4,'derivative_refinement_policy':{'maximum_scales':9,'ratio':.5,'required_consecutive_passing_scales':2,'physical_repeat_allowance_multiplier':10},
            'directional_derivatives':[{'scale':1.,'relative_difference':.0002,'empirical_resolution_fraction':.0003,'relative_difference_plus_resolution':.0005,'passes_unchanged_tolerance':False}],
            'profile_evaluations':[],'objective_repeat_difference':.0000734,'empirical_physical_objective_resolution':.000734}
        write(run/('objective-'+method)/'validation.json',data)
        write(run/('objective-'+method)/'source.json',{'sha256':'e'*64})
        write(previous/(method+'-staged')/'validation.json',data)
        point=run/('objective-'+method)/'point-003-direction-1-1-repeat'
        write(point/'qr.profile.json',{'nuisance_converged':False,'nuisance_floor_limited':True,'nuisance_floor_audit':[{'amplitude':4096.,'probes':[{'actual_reduction':-.00001}]}]})
        write(point/'closure.json',{'iterations':[{'position_change_m':1.2e-8}],'converged':True})
        write(point/'qr.3.factor.json',{'original_objective_rows':500,'rank':'full_rank'})
        write(point/'qr.3.profile.json',{'direct_cost':4093.996})
        write(point/'qr.2.nuisance_line_search.json',{'nuisance_floor_audit':[{'support_unchanged':True}],'actual_reduction':0})
        (point/'row-spool.bin').write_bytes(b'PRIVATE ROW DATA')
        (point/'profile.log').write_text('PRIVATE LOG CONTENT')
    for name in c.SCOPED:write(run/name/'result.json',{'passed':False,'status':'failed','binary_sha256':'b'*64,'error':'fixture retained'})
    write(run/'nuisance-replay/receipt.json',{'passed':False,'returncode':1,'native_sha256':'b'*64,'profile':{'nuisance_converged':False},'searches':[{'generation':1,'probes':[-1,1]}]})
    write(run/'nuisance-replay-candidate1-point012/receipt.json',{'passed':False,'returncode':1,'native_sha256':'b'*64,'error':'second exact replay failure'})
    inputs=[run/'pipeline.json',run/'objective-log_drag_ou/validation.json',run/'objective-pulses/validation.json',*[run/name/'receipt.json' for name in c.REPLAYS]]
    write(audit,{'schema':'orbit-poc-correctness-independent-audit07-v1','passed':False,'errors':['unchanged criterion failed'],
        'objective_methods':{m:{'passed':False} for m in c.METHODS},'nuisance_replays':{n:{'passed':False} for n in c.REPLAYS},
        'input_artifacts':[{'path':str(p),'status':'available','sha256':c.sha(p.read_bytes())} for p in inputs]})
    renderer,_=c.load_renderer(control)
    renderer.render(run,previous,control,report,audit)
    return dict(root=root,previous=previous,audit_path=audit,report=report,output=root/'publication-new')


def test_collect_preserves_failed_outcomes_and_every_scale(bundle):
    result=c.collect(**bundle)
    assert result['reported_pipeline_status']=='failed'
    assert result['reported_audit_passed'] is False
    assert result['reported_evidence_status']=='failed'
    assert result['release_acceptance']=='not_assessed'
    data=json.loads((bundle['output']/'objectives/log_drag_ou/validation.json').read_text())
    assert data['passed'] is False and data['directional_derivatives'][0]['scale']==1
    assert data['empirical_physical_objective_resolution']==.000734
    profile=json.loads((bundle['output']/'objectives/log_drag_ou/point-003-direction-1-1-repeat/qr.profile.json').read_text())
    assert profile['nuisance_floor_audit'][0]['amplitude']==4096


def test_no_spools_logs_private_paths_or_external_page_dependencies(bundle):
    c.collect(**bundle)
    files=list(bundle['output'].rglob('*'))
    assert not any(p.suffix in ('.bin','.log','.gz') for p in files)
    content=b'\n'.join(p.read_bytes() for p in files if p.is_file())
    assert b'PRIVATE LOG CONTENT' not in content and b'PRIVATE ROW DATA' not in content
    assert b'/home/private' not in content and str(bundle['root']).encode() not in content
    page=(bundle['output']/'index.html').read_text()
    assert '<script' not in page and '<link' not in page and 'default-src' in page


@pytest.mark.parametrize('change',[{'status':'running'},{'finished_at':None},{'final_cleanup':{'verified':False}},{'resume':{'status':'resumed'}}])
def test_requires_closed_cleanup_and_resume(bundle,change):
    path=bundle['root']/'validation-07/pipeline.json';data=json.loads(path.read_text());data.update(change);write(path,data)
    with pytest.raises(ValueError):c.collect(**bundle)
    assert not bundle['output'].exists()


@pytest.mark.parametrize('target',['audit','report','pipeline','pause','manifest'])
def test_stale_pins_refused_without_creating_output(bundle,target):
    paths={'audit':bundle['audit_path'],'report':bundle['report']/'summary.json',
        'pipeline':bundle['root']/'validation-07/pipeline.json','pause':bundle['root']/'control/interruption-03.json',
        'manifest':bundle['root']/'binaries-04/groops-fixture.build-manifest.json'}
    path=paths[target];data=json.loads(path.read_text());data['unreviewed_change']=True;write(path,data)
    with pytest.raises(ValueError):c.collect(**bundle)
    assert not bundle['output'].exists()


def test_endpoint_symlink_escape_refused(bundle,tmp_path):
    point=bundle['root']/'validation-07/objective-log_drag_ou/point-003-direction-1-1-repeat'
    private=tmp_path/'private.json';write(private,{'secret':'MUST NOT COPY'})
    (point/'qr.profile.json').unlink();(point/'qr.profile.json').symlink_to(private)
    with pytest.raises(ValueError,match='escapes'):c.collect(**bundle)
    assert not bundle['output'].exists()


def test_preserves_missing_terminal_metadata(bundle):
    path=bundle['root']/'validation-07/objective-log_drag_ou/point-003-direction-1-1-repeat/qr.profile.json';path.unlink()
    result=c.collect(**bundle)
    assert any('point-003' in p['destination'] for p in result['missing_receipts'])
    assert result['reported_pipeline_status']=='failed'


def test_new_destination_only_and_input_roots_protected(bundle):
    bundle['output'].mkdir()
    with pytest.raises(ValueError,match='NEW'):c.collect(**bundle)
    bundle['output']=bundle['root']/'source/new-evidence'
    with pytest.raises(ValueError,match='input root'):c.collect(**bundle)


def test_no_nonfinite_or_duplicate_json():
    for raw in (b'{"a":1e999}',b'{"a":NaN}',b'{"a":1,"a":2}'):
        with pytest.raises(ValueError):c.decode(raw)


def test_hashes_bind_original_and_sanitized_bytes(bundle):
    result=c.collect(**bundle)
    for item in result['files']:
        assert c.sha((bundle['output']/item['destination']).read_bytes())==item['published_sha256']
    record=next(v for v in result['files'] if v['destination']=='provenance/pipeline-07.json')
    assert record['original_sha256']!=record['published_sha256']


def rerender(bundle):
    shutil.rmtree(bundle['report'])
    renderer,_=c.load_renderer(bundle['root']/'control')
    renderer.render(bundle['root']/'validation-07',bundle['previous'],bundle['root']/'control',bundle['report'],bundle['audit_path'])


@pytest.mark.parametrize('kind',['qr.profile.json','qr.3.factor.json','qr.2.nuisance_line_search.json'])
def test_stale_raw_endpoint_dependency_rejected(bundle,kind):
    path=bundle['root']/'validation-07/objective-log_drag_ou/point-003-direction-1-1-repeat'/kind
    audit=json.loads(bundle['audit_path'].read_text())
    audit['input_artifacts'].append({'role':'objective_endpoint','path':str(path),'status':'available','sha256':c.sha(path.read_bytes())})
    write(bundle['audit_path'],audit);rerender(bundle)
    data=json.loads(path.read_text());data['changed_after_audit']=True;write(path,data)
    with pytest.raises(ValueError,match='dependency hash changed'):c.collect(**bundle)
    assert not bundle['output'].exists()


@pytest.mark.parametrize('suffix',['flight-refinement/result.json','native-tests.xml'])
def test_fixed_receipt_symlink_escape_rejected(bundle,tmp_path,suffix):
    path=bundle['root']/'validation-07'/suffix
    private=tmp_path/('private.xml' if suffix.endswith('.xml') else 'private.json')
    private.write_bytes(path.read_bytes());path.unlink();path.symlink_to(private)
    with pytest.raises(ValueError,match='escapes'):c.collect(**bundle)
    assert not bundle['output'].exists()


@pytest.mark.parametrize('change',['missing_build','duplicate_build','source','cleanup','reused_build'])
def test_fresh_build_and_closed_prior_are_required(bundle,change):
    path=bundle['root']/'validation-07/pipeline.json';data=json.loads(path.read_text())
    if change=='missing_build':data['steps']=[]
    elif change=='duplicate_build':data['steps']*=2
    elif change=='source':data['source']['sha256']='f'*64
    elif change=='cleanup':data['final_cleanup']['verified']=False
    elif change=='reused_build':data['reused_build']={'unexpected':True}
    write(path,data)
    with pytest.raises(ValueError):c.collect(**bundle)
    assert not bundle['output'].exists()


@pytest.mark.parametrize('text,private',[
    (r'failed at C:\Users\alice\secret.txt; retry later',r'C:\Users\alice'),
    ('failed at /root/private/file.txt; retry later','/root/private'),
    ('failed at /etc/private/file.txt; retry later','/etc/private'),
    ('failed at "/mnt/c/Users/Alice Smith/private.txt"; retry later','Alice Smith'),
])
def test_embedded_paths_redacted_without_removing_surrounding_error(text,private):
    value=c.scrub(text)
    assert private not in value and 'private-path-sha256:' in value
    assert value.startswith('failed at ') and value.endswith(' retry later')


def test_malformed_optional_terminal_receipt_is_explicit_invalid(bundle):
    path=bundle['root']/'validation-07/objective-log_drag_ou/point-003-direction-1-1-repeat/qr.profile.json'
    path.write_text('{"secret":"do not publish",')
    result=c.collect(**bundle)
    item=next(v for v in result['files'] if v['destination'].endswith('point-003-direction-1-1-repeat/qr.profile.json'))
    assert item['publication_status']=='invalid'
    assert item['independent_audit_coverage']=='not_in_audit_inventory'
    data=json.loads((bundle['output']/item['destination']).read_text())
    assert data['publication_receipt_status']=='invalid' and data['original_sha256']==c.sha(path.read_bytes())
    assert 'do not publish' not in (bundle['output']/item['destination']).read_text()


def test_audited_missing_or_invalid_dependencies_cannot_change(bundle):
    point=bundle['root']/'validation-07/objective-log_drag_ou/point-003-direction-1-1-repeat'
    invalid=point/'qr.profile.json';invalid.write_text('{broken')
    missing=point/'qr.99.profile.json'
    audit=json.loads(bundle['audit_path'].read_text())
    audit['input_artifacts'] += [{'role':'failed_endpoint','path':str(invalid),'status':'invalid','sha256':c.sha(invalid.read_bytes())},
        {'role':'failed_endpoint','path':str(missing),'status':'missing'}]
    write(bundle['audit_path'],audit);rerender(bundle)
    result=c.collect(**bundle)
    assert any(v['status']=='invalid' for v in result['verified_independent_audit_dependencies'])
    missing.write_text('{}');bundle['output']=bundle['root']/'publication-second'
    with pytest.raises(ValueError,match='status changed'):c.collect(**bundle)


def test_uncopied_audit_dependency_also_must_remain_pinned(bundle):
    path=bundle['root']/'validation-07/nuisance-replay/qr.1.nuisance_line_search.json'
    write(path,{'iteration':1})
    audit=json.loads(bundle['audit_path'].read_text())
    audit['input_artifacts'].append({'role':'nuisance_search','path':str(path),'status':'available','sha256':c.sha(path.read_bytes())})
    write(bundle['audit_path'],audit);rerender(bundle)
    write(path,{'iteration':2})
    with pytest.raises(ValueError,match='hash changed'):c.collect(**bundle)


def test_missing_audited_dependency_appearing_during_collection_is_rejected(bundle,monkeypatch):
    path=bundle['root']/'validation-07/nuisance-replay/qr.99.profile.json'
    audit=json.loads(bundle['audit_path'].read_text())
    audit['input_artifacts'].append({'role':'missing_terminal','path':str(path),'status':'missing'})
    write(bundle['audit_path'],audit);rerender(bundle)
    original=c.read
    def mutation_at_manifest(source):
        if Path(source)==Path(c.__file__):write(path,{'late':True})
        return original(source)
    monkeypatch.setattr(c,'read',mutation_at_manifest)
    with pytest.raises(ValueError,match='availability changed'):c.collect(**bundle)
    assert not bundle['output'].exists()


@pytest.mark.parametrize('value,prefix',[
    ('-I/mnt/d/private/source','-I'),('-L/home/private/lib','-L'),
    ('c++ -I/mnt/d/private/source -O3','c++ -I'),
    (r'-IC:\Users\alice\private\include','-I'),
])
def test_compiler_option_paths_are_redacted(value,prefix):
    result=c.scrub(value)
    assert result.startswith(prefix+'private-path-sha256:')
    assert '/mnt/' not in result and '/home/' not in result and r'C:\Users' not in result
    if value.endswith(' -O3'):assert result.endswith(' -O3')


@pytest.mark.parametrize('path', ['/mnt/d/file',r'C:\Users\alice\file'])
@pytest.mark.parametrize('suffix',[': objective failed at h=0.25','\nobjective failed at h=0.25'])
def test_leading_absolute_path_keeps_diagnostic_suffix(path,suffix):
    result=c.scrub(path+suffix)
    assert result=='private-path-sha256:'+c.sha(path.encode())+suffix


@pytest.mark.parametrize('attempt',['validation-01','validation-07'])
def test_malformed_optional_junit_is_explicit_invalid(bundle,attempt):
    path=bundle['root']/attempt/'native-tests.xml'
    path.write_text('<testsuite secret="DO NOT PUBLISH"><testcase')
    rerender(bundle)
    result=c.collect(**bundle)
    destination='native-tests.xml' if attempt=='validation-07' else 'historical/native-tests-01.xml'
    entry=next(v for v in result['files'] if v['destination']==destination)
    assert entry['publication_status']=='invalid'
    published=(bundle['output']/destination).read_text()
    assert '<invalidReceipt' in published and c.sha(path.read_bytes()) in published
    assert 'DO NOT PUBLISH' not in published and '<testcase' not in published
    assert entry['transformation']=='invalid original receipt represented by hash-only descriptor'


def test_both_failed_replays_and_prior_candidate_are_published(bundle):
    result=c.collect(**bundle)
    assert result['reported_nuisance_replays']=={name:'failed' for name in c.REPLAYS}
    for name in c.REPLAYS:
        data=json.loads((bundle['output']/name/'receipt.json').read_text())
        assert data['passed'] is False
    assert (bundle['output']/'historical/pipeline-02.json').is_file()
    summary=json.loads((bundle['output']/'summary.json').read_text())
    assert len(summary['nuisance_replays'])==2
    assert summary['release_acceptance']=='not_assessed'


def test_second_replay_stale_receipt_rejected(bundle):
    path=bundle['root']/'validation-07/nuisance-replay-candidate1-point012/receipt.json'
    data=json.loads(path.read_text());data['error']='changed';write(path,data)
    with pytest.raises(ValueError):c.collect(**bundle)
    assert not bundle['output'].exists()


def test_second_replay_missing_is_publishable_as_missing(bundle):
    path=bundle['root']/'validation-07/nuisance-replay-candidate1-point012/receipt.json';path.unlink()
    data=json.loads(bundle['audit_path'].read_text())
    for pin in data['input_artifacts']:
        if pin['path']==str(path):pin.clear();pin.update(path=str(path),status='missing')
    write(bundle['audit_path'],data);rerender(bundle)
    result=c.collect(**bundle)
    assert result['reported_nuisance_replays']['nuisance-replay-candidate1-point012']=='missing'
    assert any(v['destination']=='nuisance-replay-candidate1-point012/receipt.json' for v in result['missing_receipts'])


def test_second_replay_symlink_escape_rejected(bundle,tmp_path):
    path=bundle['root']/'validation-07/nuisance-replay-candidate1-point012/receipt.json'
    other=tmp_path/'private.json';other.write_bytes(path.read_bytes());path.unlink();path.symlink_to(other)
    with pytest.raises(ValueError,match='escapes'):c.collect(**bundle)
    assert not bundle['output'].exists()


def test_altered_historical_attempt_cannot_be_relabelled_as_preserved(bundle):
    path=bundle['root']/'validation-01/pipeline.json';data=json.loads(path.read_text());data['unrelated_failed_attempt']=True;write(path,data)
    with pytest.raises(ValueError,match='does not bind validation01'):c.collect(**bundle)
    assert not bundle['output'].exists()


def test_recovery_resume_must_remain_not_applicable(bundle):
    path=bundle['root']/'validation-07/pipeline.json';data=json.loads(path.read_text());data['resume']['invented']=True;write(path,data)
    with pytest.raises(ValueError,match='fabricate'):c.collect(**bundle)
    assert not bundle['output'].exists()


def test_interrupted03_is_preserved_without_fabricated_results(bundle):
    result=c.collect(**bundle)
    assert result['prior_attempt03_classification']=='interrupted_before_native_validation'
    interrupted=json.loads((bundle['output']/'historical/pipeline-03.json').read_text())
    assert interrupted['status']=='running' and not interrupted.get('native')
    assert not (bundle['output']/'historical/native-tests-03.xml').exists()
    assert result['campaign_resume']=='not_applicable'
    assert 'interrupted the build before' in (bundle['output']/'index.html').read_text()

@pytest.mark.parametrize('change',['boot','native','tests','claim'])
def test_interruption_provenance_cannot_be_changed(bundle,change):
    path=bundle['root']/'control/interruption-03.json';data=json.loads(path.read_text())
    if change=='boot':data['observed_boot_id']=data['previous_boot_id']
    elif change=='native':data['native_binary_produced']=True
    elif change=='tests':data['native_tests_produced']=True
    else:data['status']='scientific_failure'
    write(path,data)
    with pytest.raises(ValueError):c.collect(**bundle)
    assert not bundle['output'].exists()


def test_terminal_build_failure_preserves_missing_native_results(bundle):
    pipeline_path=bundle['root']/'validation-07/pipeline.json'
    pipeline=json.loads(pipeline_path.read_text());pipeline.pop('native')
    pipeline['steps'][0].update(status='failed',returncode=2)
    pipeline['error']='Compiler interrupted before executable creation'
    write(pipeline_path,pipeline)
    (bundle['root']/'validation-07/native-tests.xml').unlink()
    audit=json.loads(bundle['audit_path'].read_text())
    for item in audit['input_artifacts']:
        if item['path']==str(pipeline_path):item['sha256']=c.sha(pipeline_path.read_bytes())
    write(bundle['audit_path'],audit);rerender(bundle)
    result=c.collect(**bundle)
    assert result['reported_pipeline_status']=='failed' and result['native_sha256'] is None
    assert any(item['destination']=='provenance/build-manifest.json' and item['status']=='not_produced' for item in result['missing_receipts'])
    assert not (bundle['output']/'native-tests.xml').exists()


def test_real_driver_artifact_bytes_field_is_preserved(bundle):
    path=bundle['root']/'validation-07/pipeline.json';data=json.loads(path.read_text())
    data['required_pins']['bytes']=(bundle['root']/'control/candidate07-pins.json').stat().st_size
    write(path,data)
    audit=json.loads(bundle['audit_path'].read_text())
    for item in audit['input_artifacts']:
        if item['path']==str(path):item['sha256']=c.sha(path.read_bytes())
    write(bundle['audit_path'],audit);rerender(bundle)
    assert c.collect(**bundle)['reported_pipeline_status']=='failed'


def test_backend_and_binary_replay_dependencies_remain_distinct(bundle):
    source=bundle['root']/'source-04/src/orbit_poc/numerics/backend.py';source.parent.mkdir(parents=True);source.write_text('# source validator')
    artifact={'role':'backend_validator_source','path':str(source),'sha256':c.sha(source.read_bytes()),'status':'available','bytes':source.stat().st_size}
    audit=json.loads(bundle['audit_path'].read_text());audit['input_artifacts'].append(artifact)
    write(bundle['audit_path'],audit);rerender(bundle)
    result=c.collect(**bundle)
    assert any(item['role']=='backend_validator_source' for item in result['verified_independent_audit_dependencies'])
