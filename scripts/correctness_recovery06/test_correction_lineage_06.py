"""Correction lineage mutation fixtures; no native execution or real-source edits."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import pytest
from recovery_fixture_06 import install,write,pin

spec=importlib.util.spec_from_file_location('lineage06',Path(__file__).with_name('recovery_evidence_06.py'))
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
    original=json.loads(Path(pins['source_freeze']['path']).read_bytes())['source']['files']
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
