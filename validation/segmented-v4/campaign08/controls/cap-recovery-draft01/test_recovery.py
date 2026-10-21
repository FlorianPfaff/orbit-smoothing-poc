from pathlib import Path
import copy
import importlib.util
import json
import pytest

spec = importlib.util.spec_from_file_location('recovery', Path(__file__).with_name('derive_campaign08.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
C = Path('/mnt/d/orbit-segmented-v4/control')


@pytest.fixture
def actual():
    p = C / 'campaign-assembly07-packet01/actual-readback'
    load = lambda name: json.loads((p / name).read_text())
    inv = json.loads((C / 'direct-sealing05-terminal01/sealed/invocation.json').read_text())
    return [inv, load('host-plan.json'), load('launch-pins.json'), load('host-view-plan.json'),
            {'path': str(m.WRAPPER), 'sha256': 'a' * 64},
            {'path': str(m.BIN), 'sha256': 'b' * 64}, str(m.NEW)]


def test_actual_frozen_scientific_and_mount_metadata_remain_exact(actual):
    before = copy.deepcopy(actual)
    inv, host, launch, view = m.derive(*actual)
    for key, value in actual[0].items():
        if key not in {'wrapper', 'bubblewrap'}:
            assert inv[key] == value
    for key, value in actual[1].items():
        if key not in {'wrapper', 'control_root'}:
            assert host[key] == value
    assert {k: v for k, v in launch.items() if k != 'control_root'} == {k: v for k, v in actual[2].items() if k != 'control_root'}
    assert view == actual[3]
    assert actual == before
    assert host['config']['sha256'] == '33cf305ada15863e2ee04e57390707344ed045a9fc712efc3f5e6e9247656378'
    assert inv['mount_plan']['sha256'] == '937e2bf3cb2dae31e459950f912593058cf2f58a30cc77c218794fe295ee6826'


@pytest.mark.parametrize('kind', ['old_control', 'launch_control', 'old_wrapper', 'old_mount', 'resume', 'new_wrapper', 'new_binary', 'new_control'])
def test_reject_nonpermitted_recovery_delta(actual, kind):
    if kind == 'old_control': actual[1]['control_root'] += '-changed'
    if kind == 'launch_control': actual[2]['control_root'] += '-changed'
    if kind == 'old_wrapper': actual[1]['wrapper']['sha256'] = '0' * 64
    if kind == 'old_mount': actual[3]['mount_plan']['sha256'] = '0' * 64
    if kind == 'resume': actual[0]['resume_planner'] = {'path': '/resume', 'sha256': '0' * 64}
    if kind == 'new_wrapper': actual[4]['path'] += '-changed'
    if kind == 'new_binary': actual[5]['path'] += '-changed'
    if kind == 'new_control': actual[6] += '-changed'
    with pytest.raises(ValueError): m.derive(*actual)


@pytest.fixture
def writable(tmp_path):
    rows = []
    for kind in ('attempts', 'temporary', 'lock'):
        path = tmp_path / kind
        if kind == 'lock': path.touch()
        else: path.mkdir()
        stat = path.stat()
        rows.append({'kind': kind, 'source': str(path), 'identity': {'device': stat.st_dev, 'inode': stat.st_ino}})
    return {'writable_mounts': rows}


def test_actual_empty_backing_checks(writable):
    m.empty_writables(writable)


@pytest.mark.parametrize('kind', ['attempts', 'temporary', 'lock', 'inode', 'missing', 'extra'])
def test_existing_output_or_changed_identity_cannot_be_reused(writable, kind):
    rows = writable['writable_mounts']
    if kind in {'attempts', 'temporary'}:
        path = Path(next(r['source'] for r in rows if r['kind'] == kind)) / 'preserve'
        path.write_text('existing output')
    if kind == 'lock': Path(rows[2]['source']).write_text('changed')
    if kind == 'inode': rows[0]['identity']['inode'] += 1
    if kind == 'missing': rows.pop()
    if kind == 'extra': rows.append(copy.deepcopy(rows[0]))
    with pytest.raises(ValueError): m.empty_writables(writable)
    if kind in {'attempts', 'temporary'}: assert path.read_text() == 'existing output'


@pytest.mark.parametrize('kind', ['build_status', 'binary_hash', 'binary_path', 'wrapper_status', 'wrapper_hash', 'wrapper_binary'])
def test_review_must_accept_exact_corrected_controls(actual, kind):
    request = {'wrapper': actual[4], 'bubblewrap': actual[5]}
    build = {'status': 'accepted_cap_only_control_build', 'binary': copy.deepcopy(actual[5])}
    review = {'status': 'accepted_exact_bubblewrap_pin_change', 'wrapper': copy.deepcopy(actual[4]), 'bubblewrap': copy.deepcopy(actual[5])}
    m.accepted_correction(request, build, review)
    if kind == 'build_status': build['status'] = 'pending'
    if kind == 'binary_hash': build['binary']['sha256'] = '0' * 64
    if kind == 'binary_path': build['binary']['path'] += '-changed'
    if kind == 'wrapper_status': review['status'] = 'pending'
    if kind == 'wrapper_hash': review['wrapper']['sha256'] = '0' * 64
    if kind == 'wrapper_binary': review['bubblewrap']['sha256'] = '0' * 64
    with pytest.raises(ValueError): m.accepted_correction(request, build, review)


@pytest.mark.parametrize('name', [*m.OUTPUTS, 'pipeline.json', 'campaign-launch.json', 'campaign-driver.log'])
def test_existing_recovery_output_is_preserved(tmp_path, monkeypatch, name):
    monkeypatch.setattr(m, 'NEW', tmp_path)
    stat = tmp_path.stat()
    identity = {'path': str(tmp_path), 'device': stat.st_dev, 'inode': stat.st_ino}
    m.fresh_control(identity)
    path = tmp_path / name
    path.write_bytes(b'preserved earlier attempt')
    with pytest.raises(ValueError, match='Preserve earlier'): m.fresh_control(identity)
    with pytest.raises(FileExistsError): m.write_new(path, {'overwritten': True})
    assert path.read_bytes() == b'preserved earlier attempt'


def test_unknown_request_cannot_start_context():
    with pytest.raises(ValueError, match='Unknown recovery options'):
        m.context({'schema': 'orbit-poc-campaign08-cap-recovery-request-v1', 'extra': True})
