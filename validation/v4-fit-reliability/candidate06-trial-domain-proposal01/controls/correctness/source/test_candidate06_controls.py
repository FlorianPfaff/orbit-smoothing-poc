"""Pure candidate06 control boundaries; no numerical gate or native process."""
from pathlib import Path
from unittest.mock import patch
import copy
import importlib.util
import json
import xml.etree.ElementTree as ET

import pytest

from test_reference_gates09 import g
from test_reference_recovery import r


EXPECTED_EIGHT = ('synthetic-refinement-log_drag_ou', 'synthetic-refinement-pulses',
                  'flight-refinement', 'eccentric-24h-refinement', 'objective-log_drag_ou',
                  'objective-pulses', 'nuisance-replay', 'nuisance-replay-candidate1-point012')


def test_exact_native_and_correction_then_original_eight_order():
    validation, _ = g.api()
    assert g.STAGES == ('native-tests', 'correction-tests', *EXPECTED_EIGHT)
    assert tuple(validation.GATE1) == g.STAGES
    assert len(g.STAGES) == len(set(g.STAGES)) == 10


def test_unknown_stage_fails_before_plan_read_or_any_subprocess():
    with patch.object(g, 'checked_plan') as check, patch.object(g.subprocess, 'run') as run:
        with pytest.raises(ValueError, match='Unknown correctness stage'):
            g.stage_worker('/nonexistent', 'bad', 'unexpected-stage')
        check.assert_not_called()
        run.assert_not_called()


@pytest.fixture
def source_fixture(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'input.py').write_text('UNCHANGED = True\n')
    snapshot = tmp_path / 'source-snapshot.json'
    snapshot.write_text(json.dumps({'files': [{'relative_path': 'input.py', 'sha256': g.sha(source/'input.py')}]}))
    monkeypatch.setattr(g, 'SOURCE', source)
    monkeypatch.setattr(g, 'CANDIDATE_SNAPSHOT', snapshot)
    monkeypatch.setattr(g, 'CANDIDATE_SNAPSHOT_SHA256', g.sha(snapshot))
    return source, snapshot


def test_exact_source_fixture_passes(source_fixture):
    assert g.verify_candidate_source() == g.pin(source_fixture[1])


@pytest.mark.parametrize('change', ['modified', 'added', 'missing', 'symlink_file', 'symlink_directory', 'changed_snapshot'])
def test_source_drift_and_shadow_imports_rejected(source_fixture, change):
    source, snapshot = source_fixture
    if change == 'modified': (source/'input.py').write_text('changed')
    if change == 'added': (source/'shadow.py').write_text('shadow')
    if change == 'missing': (source/'input.py').unlink()
    if change == 'symlink_file':
        target = source.parent/'same.py'; target.write_bytes((source/'input.py').read_bytes())
        (source/'input.py').unlink(); (source/'input.py').symlink_to(target)
    if change == 'symlink_directory': (source/'shadow_package').symlink_to(source.parent, target_is_directory=True)
    if change == 'changed_snapshot': snapshot.write_text(json.dumps({'files': []}))
    with pytest.raises(ValueError): g.verify_candidate_source()


def minimal_plan(tmp_path):
    plan = {'schema': 'orbit-poc-candidate06-correctness-plan-v1', 'stages': list(g.STAGES),
            'environment': g.base_env(), 'cpu': 4,
            'controller_limits': {'readonly_inventory_preflight_seconds': 1800},
            'limits': {'process_tree_rss_bytes': 8*1024**3, 'min_free_disk_bytes': 16*1024**3},
            'runner': {'path': str(Path(g.__file__).absolute())},
            'recovery': {'preparation_admission': {'boot_id': 'obsolete-boot'}}}
    path = tmp_path/'plan.json'; path.write_text(json.dumps(plan))
    return path


def test_old_boot_plan_rejected_before_dependency_imports(tmp_path):
    path = minimal_plan(tmp_path)
    with patch.object(g, 'api') as api, patch.object(g, 'verify_candidate_source') as source:
        with pytest.raises(ValueError, match='different boot'): g.checked_plan(path, g.sha(path))
        api.assert_not_called(); source.assert_not_called()


def test_unknown_or_reordered_stages_fail_closed(tmp_path):
    for index, stages in enumerate([list(g.STAGES[:-1]), list(reversed(g.STAGES)), [*g.STAGES, 'extra']]):
        root=tmp_path/str(index); root.mkdir(); path=minimal_plan(root)
        plan=g.read(path); plan['stages']=stages; path.write_text(json.dumps(plan))
        with pytest.raises(ValueError, match='protocol differs'):g.checked_plan(path,g.sha(path))


def junit_fixture(path, inventory):
    root=ET.Element('testsuites'); suite=ET.SubElement(root,'testsuite', tests=str(len(inventory)))
    for row in inventory: ET.SubElement(suite,'testcase',**row)
    ET.ElementTree(root).write(path)
    return root


@pytest.mark.parametrize('stage,key,count', [('native-tests','original_native_tests',106),('correction-tests','correctness_tests',51)])
def test_exact_157_junit_inventory_and_failure_rejection(tmp_path, stage, key, count):
    validation,_=g.api()
    from orbit_poc.segmented.report import fixed_test_inventory
    inventory=fixed_test_inventory(key)
    assert len(inventory)==count
    path=tmp_path/'tests.xml';junit_fixture(path,inventory)
    assert validation.junit(path,stage)['tests']==count
    for changed in (inventory[:-1], inventory+[inventory[-1]], list(reversed(inventory))):
        junit_fixture(path,changed)
        with pytest.raises(ValueError): validation.junit(path,stage)
    wrong=copy.deepcopy(inventory);wrong[-1]['name']='stale-or-other-test'
    junit_fixture(path,wrong)
    with pytest.raises(ValueError):validation.junit(path,stage)
    for tag in ('failure','error','skipped'):
        xml=junit_fixture(path,inventory);ET.SubElement(xml.find('.//testcase'),tag)
        ET.ElementTree(xml).write(path)
        with pytest.raises(ValueError): validation.junit(path,stage)


def test_original14_input_hashes_unchanged_and_replays_distinct():
    validation,_=g.api()
    old=Path('/mnt/d/orbit-v41-recovery01/candidate04/source/src/orbit_poc/segmented/validation_reference.py')
    spec=importlib.util.spec_from_file_location('old_reference_constants',old)
    module=importlib.util.module_from_spec(spec);exec(compile(old.read_bytes(),str(old),'exec'),module.__dict__)
    actual=validation.original_input_hashes()
    assert actual==module.ORIGINAL_INPUT_HASHES and len(actual)==14
    assert actual['old_nuisance_replay']!=actual['candidate1_nuisance_replay']
    for suffix in ('variational','reference','density'):
        assert actual['old_replay_'+suffix]!=actual['new_replay_'+suffix]


def test_launcher_uses_only_whitelisted_environment():
    required={'HOME':'/home/emper','PATH':'/usr/bin:/bin','OMP_NUM_THREADS':'1'}
    inherited={**required,'LD_PRELOAD':'unapproved.so','PYTHONHOME':'unapproved','ORBIT_POC_DONOR':'old-fit'}
    assert r.inherited_environment(required,inherited)==required
    assert inherited['LD_PRELOAD']=='unapproved.so'


def test_native_test_environment_pins_same_binary_and_single_threads():
    for stage in ('native-tests','correction-tests'):
        environment=g.planned_stage_env(Path('/new-output')/stage)
        assert environment['ORBIT_POC_V31_NATIVE']==environment['ORBIT_POC_CORRECTNESS_NATIVE']==environment['ORBIT_POC_GROOPS']
        assert environment['PYTEST_DISABLE_PLUGIN_AUTOLOAD']=='1'
        assert all(environment[name]=='1' for name in g.THREADS)
        assert environment['PYTHONPATH']==str(g.SOURCE/'src')
