"""Fabricated restart/admission/source/replay identity evidence; no native work."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import pytest
from recovery_fixture_04 import install,write,pin

spec=importlib.util.spec_from_file_location('recovery04',Path(__file__).with_name('recovery_evidence_04.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

@pytest.fixture
def bundle(tmp_path):
    pipeline,pins=install(tmp_path,{'status':'failed'})
    def reader(item,role):
        assert pin(item['path'])==item
        return json.loads(Path(item['path']).read_text())
    return tmp_path,pipeline,pins,reader

def test_remote_execution_boot_independent_of_local_restart(bundle):
    root,pipeline,pins,reader=bundle
    proof=r.validate_recovery(pipeline,pins,reader)
    assert proof['status']=='verified'
    assert proof['execution']['host']['boot_id']=='remote-boot'
    assert proof['interrupted_previous']['record']['observed_boot_id']=='new-local-boot'
    assert proof['strict_convergence_or_covariance_approved'] is False
    assert proof['campaign_resume']=='not_applicable'

@pytest.mark.parametrize('change',['boot','hostname','conflict','missing_admission','policy','resume','pause','count','files','source','inputs','replay_alias'])
def test_fail_closed_recovery_contract(bundle,change):
    root,pipeline,pins,reader=bundle
    if change=='boot':pipeline['admission']['boot_id']='wrong'
    elif change=='hostname':pipeline['admission']['hostname']='wrong'
    elif change=='conflict':pipeline['admission']['conflicting_processes']=[{'pid':44}]
    elif change=='missing_admission':pipeline.pop('admission')
    elif change=='policy':pipeline['admission']['policy']='parallel_unowned'
    elif change=='resume':pipeline['resume']['status']='resumed'
    elif change=='pause':pipeline['pause_receipt']={'status':'paused'}
    elif change=='count':pins['expected_native_test_count']=105
    elif change=='files':pins['source_file_count']=759
    elif change=='source':pipeline['source']['files']['changed']='f'*64
    elif change=='inputs':pins['input_artifacts']['initial_state']['sha256']='f'*64
    elif change=='replay_alias':pins['input_artifacts']['candidate1_nuisance_replay']=pins['input_artifacts']['old_nuisance_replay']
    with pytest.raises(ValueError):r.validate_recovery(pipeline,pins,reader)

@pytest.mark.parametrize('change',['same_boot','native','tests','status','completed_build','pipeline_native','pipeline_tests'])
def test_interrupted_build_is_not_scientific_failure_or_success(bundle,change):
    root,pipeline,pins,reader=bundle
    item=pins['interruption_record'];restart=json.loads(Path(item['path']).read_text())
    priorpath=Path(restart['prior_pipeline']['path']);prior=json.loads(priorpath.read_text())
    if change=='same_boot':restart['observed_boot_id']=restart['previous_boot_id']
    elif change=='native':restart['native_binary_produced']=True
    elif change=='tests':restart['native_tests_produced']=True
    elif change=='status':restart['status']='failed'
    elif change=='completed_build':prior['steps'][0]['status']='passed'
    elif change=='pipeline_native':prior['native']={'sha256':'a'*64}
    elif change=='pipeline_tests':prior['steps'].append({'name':'native-tests'})
    write(priorpath,prior);restart['prior_pipeline']=pin(priorpath)
    write(item['path'],restart);pins['interruption_record']=pipeline['interruption_record']=pin(item['path'])
    with pytest.raises(ValueError):r.validate_recovery(pipeline,pins,reader)

def test_longest_pinned_alias_preserves_logical_layout():
    execution={'read_only_bindings':[{'source':'/remote/archive','target':'/mnt/d/archive'},
        {'source':'/remote/specific','target':'/mnt/d/archive/fixed'}]}
    assert r.host_path('/mnt/d/archive/fixed/profile.xml',execution)==Path('/remote/specific/profile.xml')
    assert r.host_path('/mnt/d/archive/other',execution)==Path('/remote/archive/other')
    assert r.host_path('/remote/run',execution)==Path('/remote/run')

@pytest.mark.parametrize('rows',[[{'source':'/a','target':'/old'},{'source':'/b','target':'/old'}],[{'source':'relative','target':'/old'}],[{'source':'/a/../b','target':'/old'}]])
def test_ambiguous_or_relative_aliases_rejected(rows):
    with pytest.raises(ValueError):r.host_path('/old/file',{'read_only_bindings':rows})


def test_canonical_interruption_pin_matches_actual_remote_journal_path(bundle):
    root,pipeline,pins,reader=bundle
    execution=json.loads(Path(pipeline['execution']['path']).read_text())
    execution['read_only_bindings']=[{'source':str(root/'control'),'target':'/canonical/control'}]
    write(pipeline['execution']['path'],execution)
    pipeline['execution']=pin(pipeline['execution']['path']);pins['execution_sha256']=pipeline['execution']['sha256']
    pins['interruption_record']={**pins['interruption_record'],'path':'/canonical/control/interruption-03.json'}
    proof=r.validate_recovery(pipeline,pins,reader)
    assert proof['status']=='verified'
