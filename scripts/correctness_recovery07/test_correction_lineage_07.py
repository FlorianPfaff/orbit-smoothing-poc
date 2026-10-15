"""Correction lineage mutation fixtures; no native execution or real-source edits."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import pytest
from recovery_fixture_07 import install,write,pin

spec=importlib.util.spec_from_file_location('lineage07',Path(__file__).with_name('recovery_evidence_07.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


@pytest.fixture
def setup(tmp_path):
    pipeline,pins=install(tmp_path,{'status':'failed'})
    def read(item,role):
        assert pin(item['path'])==item
        return json.loads(Path(item['path']).read_bytes())
    return pipeline,pins,read


def rewrite_lineage(pipeline,pins,change):
    path=Path(pins['correction_lineage']['path']);value=json.loads(path.read_bytes());change(value)
    write(path,value);pins['correction_lineage']=pipeline['correction_lineage']=pin(path)


def rewrite_current(pipeline,pins,change):
    original=json.loads(Path(pins['previous_source_freeze']['path']).read_bytes())['source']['files']
    current=deepcopy(pipeline['source']);change(current['files']);current['sha256']=m.digest(current['files'])
    pipeline['source']=current;pins.update(source_sha256=current['sha256'],source_file_count=len(current['files']))
    path=Path(pins['new_source_freeze']['path']);value=json.loads(path.read_bytes());value['source']=current
    write(path,value);pins['new_source_freeze']=pin(path)
    changes={name:{'before':original.get(name),'after':value} for name,value in current['files'].items() if original.get(name)!=value}
    pins['allowed_correction_paths']=sorted(changes)
    rewrite_lineage(pipeline,pins,lambda d:d.update(new_source_freeze=pin(path),new_source_sha256=current['sha256'],changes=changes))


def test_explicit_correction_preserves_original_and_both_failures(setup):
    pipeline,pins,read=setup;result=m.validate_recovery(pipeline,pins,read)
    correction=result['correction'];assert correction['classification']=='separately_versioned_numerical_correction'
    assert correction['scientific_gate_acceptance'] is False
    assert correction['preserved_failed_attempts']['04']['record'].get('native') is None
    assert correction['preserved_failed_attempts']['05']['record']['native']
    assert result['interrupted_previous']['pipeline']['source']!=pipeline['source']
    assert correction['regression_suite']==pins['regression_suite']


@pytest.mark.parametrize('name',['tests/test_numerics_native_qr.py','scripts/validate_numerics_objective.py','src/orbit_poc/numerics/backend.py'])
def test_original_gate_and_tests_cannot_change_even_if_new_pins_rehashed(setup,name):
    pipeline,pins,read=setup;rewrite_current(pipeline,pins,lambda files:files.update({name:'e'*64}))
    with pytest.raises(ValueError,match='Original tests or numerical gate'):m.validate_recovery(pipeline,pins,read)


def test_source_deletion_cannot_be_authorized_by_rehashed_current_freeze(setup):
    pipeline,pins,read=setup;rewrite_current(pipeline,pins,lambda files:files.pop('fixture-10'))
    with pytest.raises(ValueError,match='cannot delete'):m.validate_recovery(pipeline,pins,read)


@pytest.mark.parametrize('change',[
    lambda d:d['changes']['fixture-0'].update(before='f'*64),
    lambda d:d['changes']['fixture-0'].update(after='f'*64),
    lambda d:d.update(original_source_sha256='f'*64),
    lambda d:d.update(new_source_sha256='f'*64),
    lambda d:d.update(failed_pipeline05=d['failed_pipeline04']),
    lambda d:d['new_source_freeze'].update(sha256='f'*64),
])
def test_lineage_hashes_and_distinct_failure_attribution(setup,change):
    pipeline,pins,read=setup;rewrite_lineage(pipeline,pins,change)
    with pytest.raises((ValueError,AssertionError)):m.validate_recovery(pipeline,pins,read)


@pytest.mark.parametrize('field,value',[('status','passed'),('final_cleanup',{'verified':False}),('source',{}),('resume',{'status':'resumed'})])
def test_terminal05_failure_cannot_be_reclassified(setup,field,value):
    pipeline,pins,read=setup
    def change(d):
        item=d['failed_pipeline05'];record=json.loads(Path(item['path']).read_bytes());record[field]=value
        write(item['path'],record);d['failed_pipeline05']=pin(item['path'])
    rewrite_lineage(pipeline,pins,change)
    with pytest.raises(ValueError):m.validate_recovery(pipeline,pins,read)


@pytest.mark.parametrize('change',[
    lambda d:d.update(expected_count=0),
    lambda d:d.update(expected_count=True),
    lambda d:d.update(files=['tests/test_numerics_native_qr.py']),
    lambda d:d.update(files=[d['files'][0],d['files'][0]]),
])
def test_regressions_are_distinct_new_tests(setup,change):
    pipeline,pins,read=setup;change(pins['regression_suite'])
    with pytest.raises(ValueError,match='Separate correction regression'):m.validate_recovery(pipeline,pins,read)


def test_unrecorded_path_change_is_rejected(setup):
    pipeline,pins,read=setup;pins['allowed_correction_paths'].append('groops/extension/unreviewed.h')
    with pytest.raises(ValueError,match='exact reviewed'):m.validate_recovery(pipeline,pins,read)


def test_journal_cannot_claim_other_correction(setup):
    pipeline,pins,read=setup;pipeline['correction_lineage']['sha256']='f'*64
    # Break object aliasing deliberately: the frozen pin is still the actual file.
    pins['correction_lineage']=pin(pins['correction_lineage']['path'])
    with pytest.raises(ValueError,match='Executed correction lineage'):m.validate_recovery(pipeline,pins,read)


@pytest.mark.parametrize('field,value',[
    ('status','passed'),('final_cleanup',{'verified':False}),('source',{}),
    ('finished_at',None),('native',None),('resume',{'status':'resumed'})])
def test_failed06_is_retained_with_its_own_source_and_terminal_identity(setup,field,value):
    pipeline,pins,read=setup
    def change(d):
        item=d['failed_pipeline06'];record=json.loads(Path(item['path']).read_bytes());record[field]=value
        write(item['path'],record);d['failed_pipeline06']=pin(item['path'])
    rewrite_lineage(pipeline,pins,change)
    with pytest.raises(ValueError):m.validate_recovery(pipeline,pins,read)


@pytest.mark.parametrize('number',['04','05'])
def test_failed06_cannot_be_replaced_by_an_earlier_attempt(setup,number):
    pipeline,pins,read=setup
    rewrite_lineage(pipeline,pins,lambda d:d.update(failed_pipeline06=d['failed_pipeline'+number]))
    with pytest.raises(ValueError):m.validate_recovery(pipeline,pins,read)


@pytest.mark.parametrize('name',[
    'tests/test_numerics_query_precision.py','tests/test_numerics_reference_precision.py'])
def test_previous_regression_sources_remain_byte_identical(setup,name):
    pipeline,pins,read=setup;rewrite_current(pipeline,pins,lambda files:files.update({name:'f'*64}))
    with pytest.raises(ValueError,match='Original tests or numerical gate'):m.validate_recovery(pipeline,pins,read)


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(previous_source_sha256='f'*64),
    lambda d:d.update(previous_source_freeze=d['original_source_freeze']),
    lambda d:d['changes']['fixture-0'].update(before='a'*64),
])
def test_incremental_lineage_cannot_rebase_onto_original_or_forge_previous_hash(setup,mutation):
    pipeline,pins,read=setup;rewrite_lineage(pipeline,pins,mutation)
    with pytest.raises(ValueError):m.validate_recovery(pipeline,pins,read)


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(schema='orbit-poc-candidate06-source-freeze-v1'),
    lambda d:d.update(commit='a'*40),
    lambda d:d.update(commit='uncommitted'),
    lambda d:d.update(original_native_test_count=105),
    lambda d:d.update(regression_suite={'files':[], 'expected_count':19}),
])
def test_new_freeze_requires_separate_commit_schema_and_original_inventory(setup,mutation):
    pipeline,pins,read=setup;path=Path(pins['new_source_freeze']['path'])
    value=json.loads(path.read_bytes());mutation(value);write(path,value);pins['new_source_freeze']=pin(path)
    rewrite_lineage(pipeline,pins,lambda d:d.update(new_source_freeze=pin(path)))
    with pytest.raises(ValueError):m.validate_recovery(pipeline,pins,read)


def test_previous06_failure_and_new07_are_distinct_and_no_scientific_claim(setup):
    pipeline,pins,read=setup;result=m.validate_recovery(pipeline,pins,read)
    failures=result['correction']['preserved_failed_attempts']
    assert set(failures)=={'04','05','06'}
    assert failures['06']['record']['source']==result['correction']['previous_source_freeze']['source']
    assert failures['06']['record']['source']!=pipeline['source']
    assert result['strict_convergence_or_covariance_approved'] is False
