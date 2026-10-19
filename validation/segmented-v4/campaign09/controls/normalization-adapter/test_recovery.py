from pathlib import Path
import copy
import importlib.util
import json
import pytest

spec = importlib.util.spec_from_file_location('recovery', Path(__file__).with_name('derive_campaign09_normalization03.py'))
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
            {'path': str(m.BIN), 'sha256': 'b' * 64}, str(m.NEW), copy.deepcopy(inv), {'path':'/fresh/readonly.json','sha256':'c'*64}]


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
    assert view == {**actual[3], 'readonly_plan':actual[8]}
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
    review = {'bootstrap_sha256':m.BOOTSTRAP_SHA, 'status': 'accepted_checked_private_dev_bootstrap', 'wrapper': copy.deepcopy(actual[4]), 'bubblewrap': copy.deepcopy(actual[5])}
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
        m.context({'schema': 'orbit-poc-campaign09-private-dev-recovery-request-v1', 'extra': True})


@pytest.fixture
def probe_evidence(actual, tmp_path):
    inv = actual[0]
    proof = {'status':'passed','benchmark_attempts_launched':0,'fit_execution_authorized':False,'specification_file_sha256':inv['probe_spec']['sha256'],'host_verified_final_artifacts':{'allowlist_sha256':'a768ddf14c8ebb7fb11e4752c9787da407f7db77ee618176ae2946ce32c4ed3d','mount_plan_sha256':inv['mount_plan']['sha256'],'expected_completed':0},'public_readonly_checks':{'terminal_prefix':[],'validation':{'status':'passed'}}}
    cmd=[inv['taskset']['path'],'-c','24',inv['python']['path'],'-B',inv['probe_helper']['path'],'--spec',inv['probe_spec']['path'],'--sha256',inv['probe_spec']['sha256'],'--allowlist-sha256',proof['host_verified_final_artifacts']['allowlist_sha256'],'--mount-plan-sha256',inv['mount_plan']['sha256'],'--expected-completed','0']
    import hashlib
    boot={'schema':'orbit-poc-private-dev-bootstrap-result-v1','status':'passed','bootstrap_sha256':m.BOOTSTRAP_SHA,'original_command_preserved':True,'command':cmd,'original_command_sha256':hashlib.sha256(b''.join(x.encode()+b'\0' for x in cmd)).hexdigest(),'descriptors':[],'removed':[{'path':'/dev/shm'},{'path':'/dev/core','target':'/proc/kcore'}],'namespaces':{'mnt':'a','pid':'b','net':'c'},'outer_namespaces':{'mnt':'d','pid':'e','net':'f'}}
    boot_path=tmp_path/'bootstrap.json';boot_path.write_text(json.dumps(boot))
    execution = {'bootstrap':m.pin(boot_path),'status':'passed','fit_attempts':0,'cleanup':{'verified':True,'live_owned_processes':[]},'interrupted_or_timeout':False}
    proof_path=tmp_path/'proof.json';proof_path.write_text(json.dumps(proof))
    exec_path=tmp_path/'execution.json';exec_path.write_text(json.dumps(execution))
    review={'bootstrap_sha256':m.BOOTSTRAP_SHA,'bootstrap_receipt':m.pin(boot_path),'status':'accepted_actual_private_dev_namespace_probe','wrapper':actual[4],'bubblewrap':actual[5],'mount_plan':inv['mount_plan'],'allowlist_sha256':proof['host_verified_final_artifacts']['allowlist_sha256'],'probe_spec':inv['probe_spec'],'probe_status':'passed','benchmark_attempts_launched':0,'cleanup_verified':True,'attempts_empty':True,'temporary_empty':True,'proof':m.pin(proof_path),'execution':m.pin(exec_path)}
    return {'wrapper':actual[4],'bubblewrap':actual[5]},review,inv


def test_exact_actual_probe_required(probe_evidence):
    m.accepted_probe(*probe_evidence, probe_evidence[1]['allowlist_sha256'])


@pytest.mark.parametrize('key', ['status','wrapper','bubblewrap','mount_plan','allowlist_sha256','probe_spec','probe_status','benchmark_attempts_launched','cleanup_verified','attempts_empty','temporary_empty'])
def test_reject_unaccepted_or_different_probe(probe_evidence,key):
    request,review,inv=[copy.deepcopy(x) for x in probe_evidence]
    if isinstance(review[key],dict):review[key]['sha256']='0'*64
    elif isinstance(review[key],bool):review[key]=False
    elif isinstance(review[key],int):review[key]=1
    else:review[key]='changed'
    with pytest.raises(ValueError):m.accepted_probe(request,review,inv,'a768ddf14c8ebb7fb11e4752c9787da407f7db77ee618176ae2946ce32c4ed3d')


@pytest.mark.parametrize('target,key,value', [('proof','status','failed'),('proof','benchmark_attempts_launched',1),('proof','fit_execution_authorized',True),('proof','specification_file_sha256','0'*64),('execution','status','failed'),('execution','fit_attempts',1),('execution','interrupted_or_timeout',True)])
def test_reject_actual_failed_result_despite_accepted_review(probe_evidence,target,key,value):
    request,review,inv=[copy.deepcopy(x) for x in probe_evidence];path=Path(review[target]['path']);data=json.loads(path.read_text());data[key]=value;path.write_text(json.dumps(data));review[target]=m.pin(path)
    with pytest.raises(ValueError):m.accepted_probe(request,review,inv,'a768ddf14c8ebb7fb11e4752c9787da407f7db77ee618176ae2946ce32c4ed3d')


def test_actual_intervening_capture_and_review_are_pinned(monkeypatch):
    capture=json.loads((C/'campaign08-terminal01/manifest.json').read_text());review=json.loads((C/'campaign08-terminal-failure-independent-review01.json').read_text())
    request={'intervening_capture':{'path':'/capture','sha256':m.INTERVENING_CAPTURE},'intervening_review':{'path':'/audit','sha256':m.INTERVENING_REVIEW}}
    monkeypatch.setattr(m,'read',lambda pin: copy.deepcopy(capture if pin['path']=='/capture' else review))
    checked=[];monkeypatch.setattr(m,'checked',lambda pin:checked.append(pin));monkeypatch.setattr(m,'process_gone',lambda i:True)
    assert m.verified_intervening(request)==capture
    assert len(checked)==26
    monkeypatch.setattr(m,'process_gone',lambda i:False)
    with pytest.raises(ValueError):m.verified_intervening(request)


@pytest.mark.parametrize('key', ['intervening_capture','intervening_review'])
def test_wrong_intervening_identity_rejected(key):
    request={'intervening_capture':{'path':'/capture','sha256':m.INTERVENING_CAPTURE},'intervening_review':{'path':'/audit','sha256':m.INTERVENING_REVIEW}}
    request[key]['sha256']='0'*64
    with pytest.raises(ValueError):m.verified_intervening(request)

@pytest.mark.parametrize('key,value', [('status','failed'),('bootstrap_sha256','0'*64),('original_command_preserved',False),('command',['different']),('original_command_sha256','0'*64),('descriptors',[3]),('removed',[{'path':'/dev/shm'}]),('namespaces',{'mnt':'d','pid':'e','net':'f'})])
def test_reject_inexact_bootstrap_receipt(probe_evidence,key,value):
    request,review,inv=copy.deepcopy(probe_evidence)
    path=Path(review['bootstrap_receipt']['path']);data=json.loads(path.read_text());data[key]=value;path.write_text(json.dumps(data));review['bootstrap_receipt']=m.pin(path)
    ep=Path(review['execution']['path']);execution=json.loads(ep.read_text());execution['bootstrap']=review['bootstrap_receipt'];ep.write_text(json.dumps(execution));review['execution']=m.pin(ep)
    with pytest.raises(ValueError):m.accepted_probe(request,review,inv,'a768ddf14c8ebb7fb11e4752c9787da407f7db77ee618176ae2946ce32c4ed3d')


def test_execution_cannot_attribute_another_bootstrap(probe_evidence):
    request,review,inv=probe_evidence;p=Path(review['execution']['path']);d=json.loads(p.read_text());d['bootstrap']['sha256']='0'*64;p.write_text(json.dumps(d));review['execution']=m.pin(p)
    with pytest.raises(ValueError):m.accepted_probe(request,review,inv,'a768ddf14c8ebb7fb11e4752c9787da407f7db77ee618176ae2946ce32c4ed3d')


def test_frozen_failed_smoke_remains_pinned_and_stopped(monkeypatch):
    capture=json.loads((C/'loader-alias-smoke-terminal01/manifest.json').read_text());review=json.loads((C/'loader-alias-smoke-terminal-independent-review01.json').read_text());execution=json.loads((C/'loader-alias-smoke-terminal01/execution/execution.json').read_text())
    request={'smoke_failure_capture':{'path':'/capture','sha256':m.SMOKE_CAPTURE},'smoke_failure_review':{'path':'/review','sha256':m.SMOKE_REVIEW}}
    data={'/capture':capture,'/review':review,review['execution']['path']:execution};monkeypatch.setattr(m,'read',lambda p:copy.deepcopy(data[p['path']]))
    checked=[];monkeypatch.setattr(m,'checked',lambda p:checked.append(p));monkeypatch.setattr(m,'process_gone',lambda p:True)
    assert m.verified_smoke_failure(request)==capture and len(checked)==12
    monkeypatch.setattr(m,'process_gone',lambda p:False)
    with pytest.raises(ValueError):m.verified_smoke_failure(request)


@pytest.mark.parametrize('key',['smoke_failure_capture','smoke_failure_review'])
def test_failed_smoke_cannot_be_substituted(key):
    request={'smoke_failure_capture':{'path':'/capture','sha256':m.SMOKE_CAPTURE},'smoke_failure_review':{'path':'/review','sha256':m.SMOKE_REVIEW}}
    request[key]['sha256']='0'*64
    with pytest.raises(ValueError):m.verified_smoke_failure(request)
