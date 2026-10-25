"""Pure filesystem, path, capacity and namespace controls; no native execution."""
from pathlib import Path
import shutil
from types import SimpleNamespace
import pytest

from test_reference_gates09 import g


@pytest.fixture
def owned(tmp_path):
    storage = g.storage_api()
    output = tmp_path / 'output'
    output.mkdir()
    for stage in ('prepared', *g.STAGES):
        for leaf in ('tmp', 'scratch', 'row-spool'):
            (output / stage / leaf).mkdir(parents=True)
    value = storage.create(output, g.STAGES)
    yield storage, value, output
    shutil.rmtree(value['root']['path'])


def test_only_tmp_and_design_are_overmounted(owned):
    s, value, output = owned
    command = s.binds(value, output / 'objective-log_drag_ou')
    pairs = [command[i+1:i+3] for i in range(0, len(command), 3)]
    assert pairs[0] == [str(output / 'objective-log_drag_ou')]*2
    assert [row[1] for row in pairs] == [str(output/'objective-log_drag_ou'), str(output/'objective-log_drag_ou/tmp'), str(output/'objective-log_drag_ou/scratch'), '/tmp']
    assert all('row-spool' not in row[1] for row in pairs)


def test_separate_stage_inodes(owned):
    s, value, output = owned
    rows = [s.check_host(value, name)['leaves']['scratch'] for name in g.STAGES]
    assert len({(row['device'], row['inode']) for row in rows}) == len(g.STAGES)


def test_creation_refuses_existing_owned_root(owned):
    s, value, output = owned
    with pytest.raises(FileExistsError):
        s.create(output, g.STAGES)


def test_replaced_scratch_directory_is_rejected(owned):
    s, value, output = owned
    leaf = Path(value['stages'][g.STAGES[0]]['leaves']['scratch']['path'])
    leaf.rename(leaf.with_name('preserved-original'))
    leaf.mkdir()
    with pytest.raises(ValueError, match='identity changed'):
        s.check_host(value, g.STAGES[0])


def test_symlink_scratch_is_rejected(owned):
    s, value, output = owned
    leaf = Path(value['stages'][g.STAGES[0]]['leaves']['scratch']['path'])
    leaf.rmdir(); leaf.symlink_to(leaf.parent/'tmp', target_is_directory=True)
    with pytest.raises(ValueError, match='ordinary owned'):
        s.check_host(value, g.STAGES[0])


def test_changed_boot_is_rejected(owned):
    s, value, output = owned
    value['boot_id'] = 'different-boot'
    with pytest.raises(ValueError, match='different boot'):
        s.check_host(value, 'prepared')


def test_insufficient_capacity_is_rejected(owned, monkeypatch):
    s, value, output = owned
    monkeypatch.setattr(s.shutil, 'disk_usage', lambda _: SimpleNamespace(free=4095))
    with pytest.raises(ValueError, match='Insufficient'):
        s.capacity(value, 'prepared', 4096)


def test_capacity_uses_measured_free_bytes(owned, monkeypatch):
    s, value, output = owned
    monkeypatch.setattr(s.shutil, 'disk_usage', lambda _: SimpleNamespace(free=8192))
    assert s.capacity(value, 'prepared', 4096)['available_bytes'] == 8192


def test_child_must_resolve_to_original_inode(owned):
    s, value, output = owned
    with pytest.raises(ValueError, match='frozen owned'):
        s.child_identity(value, output/'prepared/scratch')


def test_outside_output_and_wrong_scratch_role_rejected(owned):
    s, value, output = owned
    with pytest.raises(ValueError):
        s.child_identity(value, output/'prepared/row-spool')
    with pytest.raises(ValueError):
        s.binds(value, output.parent/'elsewhere')


def test_candidate_conditional_selection_and_original_deadlines():
    assert g.base_env()['ORBIT_POC_NUISANCE_CONDITIONAL_QR'] == '1'
    assert len(g.STAGES) == 8
    text = Path(g.__file__).read_text()
    assert "7500 if stage.startswith('nuisance-replay') else 7200" in text
    assert g.SOURCE == Path('/mnt/d/orbit-v41-recovery01/candidate04/source')
    assert g.BUILD.name == 'build-result04.json'


def test_full_original_cleanup_certificate_retained():
    complete = {'owned_process_group_cleaned': True, 'cleanup': {'verified': True, 'empty_tree_certificate': 'kernel_ECHILD', 'remaining': []}}
    assert g.cleanup_verified(complete)
    complete['cleanup']['remaining'] = [{'pid': 1}]
    assert not g.cleanup_verified(complete)


def build_fixture():
    return {'execution': {'status': 'complete', 'returncode': 0,
            'owned_process_group_cleaned': True, 'cleanup': {'verified': True,
            'empty_tree_certificate': 'kernel_ECHILD', 'remaining': []}},
        **{key: True for key in ('inputs_and_originals_unchanged', 'boot_unchanged',
            'dependencies_unchanged', 'source_snapshot_unchanged', 'tools_unchanged')}}


@pytest.mark.parametrize('key', ('inputs_and_originals_unchanged', 'boot_unchanged', 'dependencies_unchanged', 'source_snapshot_unchanged', 'tools_unchanged'))
@pytest.mark.parametrize('missing', (False, True))
def test_build_missing_or_false_identity_guard_rejected(key, missing):
    value = build_fixture()
    if missing: del value[key]
    else: value[key] = False
    with pytest.raises(ValueError, match='verified candidate04'):
        g.validate_build(value)


@pytest.mark.parametrize('key', ('verified', 'remaining', 'empty_tree_certificate'))
def test_build_missing_cleanup_field_rejected(key):
    value = build_fixture(); del value['execution']['cleanup'][key]
    with pytest.raises(ValueError, match='kernel_ECHILD'):
        g.validate_build(value)


def test_build_complete_evidence_passes():
    g.validate_build(build_fixture())
