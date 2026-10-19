from pathlib import Path
import importlib.util
import hashlib
import json
import os
import types
import pytest

SOURCE=Path(__file__).with_name('run_alias_probe03.py')
spec=importlib.util.spec_from_file_location('smoke_review_subject', SOURCE)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

@pytest.fixture
def inv():
    return {'taskset':{'path':'/usr/bin/taskset'},'python':{'path':'/frozen/python'},
            'probe_helper':{'path':'/control/probe02.py','sha256':'probe'},
            'probe_spec':{'path':'/control/probe-spec.json','sha256':'spec'},
            'bubblewrap':{'path':'/control/bwrap16384'},'wrapper':{'path':'/control/wrapper04.py'},
            'mount_plan':{'path':'/control/mount.json'}}

@pytest.fixture
def prepared():
    return {'outer_namespaces':{k:k+':[1]' for k in ('mnt','pid','net')},'prefix':0,'mount_plan_sha256':m.MOUNT_SHA,'allowlist_sha256':m.ALLOW_SHA,
            'mount_args':['--unshare-user','--tmpfs','/','--remount-ro','/'],
            'environment':{'ONLY':'fixed'},'loader_aliases':[{'path':'/usr/lib64/libc.so.6','target':'/usr/lib/x86_64-linux-gnu/libc.so.6'}]}

@pytest.fixture
def mount(tmp_path):
    rows=[]
    for kind in ('attempts','temporary','lock'):
        p=tmp_path/kind
        p.touch() if kind=='lock' else p.mkdir()
        s=p.stat()
        rows.append({'kind':kind,'source':str(p),'target':str(p),'identity':{'device':s.st_dev,'inode':s.st_ino}})
    return {'writable_mounts':rows}

def test_exact_probe_command(inv,prepared):
    got=m.probe_command(inv,prepared)
    assert got==['/usr/bin/taskset','-c','24','/frozen/python','-B','/control/probe02.py','--spec','/control/probe-spec.json','--sha256','spec','--allowlist-sha256',m.ALLOW_SHA,'--mount-plan-sha256',m.MOUNT_SHA,'--expected-completed','0']
    assert all('campaign' not in arg for arg in got)

@pytest.mark.parametrize('key,value',[('prefix',1),('mount_plan_sha256','bad'),('allowlist_sha256','bad')])
def test_wrong_probe_identity_rejected(inv,prepared,key,value):
    prepared[key]=value
    with pytest.raises(ValueError):m.probe_command(inv,prepared)

def test_wrong_taskset_rejected(inv,prepared):
    inv['taskset']['path']='/different/taskset'
    with pytest.raises(ValueError):m.probe_command(inv,prepared)

def test_exact_three_writable_targets(mount):
    assert m.empty_writes(mount)==[(r['source'],r['target']) for r in mount['writable_mounts']]

@pytest.mark.parametrize('mode',['extra','missing','duplicate_kind','target_alias','inode','device','nonempty_directory','nonempty_lock','symlink','wrong_type'])
def test_bad_writable_targets_rejected(mount,tmp_path,mode):
    rows=mount['writable_mounts'];r=rows[0];p=Path(r['source'])
    if mode=='extra':rows.append(dict(rows[0]))
    elif mode=='missing':rows.pop()
    elif mode=='duplicate_kind':rows[1]['kind']='attempts'
    elif mode=='target_alias':r['target']=str(tmp_path/'other')
    elif mode=='inode':r['identity']['inode']+=1
    elif mode=='device':r['identity']['device']+=1
    elif mode=='nonempty_directory':(p/'unexpected').write_text('x')
    elif mode=='nonempty_lock':Path(rows[2]['source']).write_text('x')
    elif mode=='symlink':
        alias=tmp_path/'alias';alias.symlink_to(p,target_is_directory=True);r['source']=r['target']=str(alias)
    elif mode=='wrong_type':
        p.rmdir();p.touch();s=p.stat();r['identity']={'device':s.st_dev,'inode':s.st_ino}
    with pytest.raises(ValueError):m.empty_writes(mount)

def base():
    return ['/usr/bin/bwrap','--ro-bind','/','/','--bind','/any/fit-seal-control-07','/any/fit-seal-control-07','--','/unused-original-command']

def test_outer_readonly_conversion_and_exact_appended_writes(mount):
    original=base();got=m.outer_arguments({'bubblewrap':{'path':'/usr/bin/bwrap'}},original,mount)
    expected=original[:original.index('--')];expected[4]='--ro-bind'
    for r in mount['writable_mounts']:expected+=['--bind',r['source'],r['target']]
    assert got==expected
    assert original==base()
    assert got.count('--bind')==3
    assert '/unused-original-command' not in got

@pytest.mark.parametrize('mode',['missing_tail','wrong_executable','extra_bind','wrong_control_name','different_bind_targets','unshare_pid','unshare_net','die_with_parent'])
def test_invalid_outer_arguments_rejected(mount,mode):
    args=base()
    if mode=='missing_tail':args=args[:7]
    elif mode=='wrong_executable':args[0]='/usr/bin/other'
    elif mode=='extra_bind':args[7:7]=['--bind','/other','/other']
    elif mode=='wrong_control_name':args[5]=args[6]='/any/other-control'
    elif mode=='different_bind_targets':args[6]='/different/fit-seal-control-07'
    else:args[1:1]=['--'+mode.replace('_','-')]
    with pytest.raises(ValueError):m.outer_arguments({'bubblewrap':{'path':'/usr/bin/bwrap'}},args,mount)

@pytest.mark.parametrize('bad',[{}, {'schema':'unknown'}, {'schema':'orbit-poc-loader-alias-probe-smoke-v1','unknown':1}])
def test_unknown_context_options_rejected(bad):
    with pytest.raises(ValueError,match='Unknown smoke options'):m.context(bad)

def test_transport_exact_options_fd_and_direct_command(monkeypatch,tmp_path,inv,prepared,capsys):
    plan={'invocation':{'path':'/control/inv.json','sha256':'inv'}}
    path=tmp_path/'plan.json';path.write_text(json.dumps(plan));args=prepared['mount_args'].copy()
    fd=os.open('/dev/null',os.O_RDONLY)
    observed={}
    def sealed(payload):
        observed['sealed']=list(payload);return fd
    def boundary(value):
        assert value==fd;observed['boundary']=True
    def execve(binary,argv,environment):
        observed.update(binary=binary,argv=argv,environment=environment)
        raise RuntimeError('intentional exec boundary')
    s=importlib.util.spec_from_file_location("shared_bootstrap_wrapper",Path("/mnt/d/orbit-segmented-v4/control/device-bootstrap-wrapper-draft01/with_segmented_fit_namespace05.py"));wrapper=importlib.util.module_from_spec(s);s.loader.exec_module(wrapper);wrapper.descriptor_boundary=boundary
    fresh=types.SimpleNamespace(sealed_args_fd=sealed,args_bytes=lambda items:b''.join(x.encode()+b'\0' for x in items))
    command=m.probe_command(inv,prepared)
    monkeypatch.setattr(m,'context',lambda p:inv)
    monkeypatch.setattr(m,'prepare_probe',lambda p:(inv,wrapper,fresh,prepared,command))
    monkeypatch.setattr(m.os,'execve',execve)
    monkeypatch.setattr(m,'__file__',str(SOURCE))
    monkeypatch.setattr('sys.argv',['helper','--plan',str(path),'--sha256',hashlib.sha256(path.read_bytes()).hexdigest(),'--inner-host'])
    with pytest.raises(RuntimeError,match='intentional exec boundary'):m.main()
    assert observed['sealed']==args
    assert observed['argv']==[inv['bubblewrap']['path'],'--args',str(fd),'--',*wrapper.namespace_command(command,prepared['outer_namespaces'])]
    assert observed['environment']=={}
    assert observed['boundary'] is True
    with pytest.raises(OSError):os.fstat(fd)
    receipt=json.loads(capsys.readouterr().out)
    assert receipt['benchmark_attempts_launched']==0
    assert receipt['command']==command
    assert receipt['allowlist_sha256']==m.ALLOW_SHA
    assert receipt['sealed_options_sha256']==hashlib.sha256(fresh.args_bytes(args)).hexdigest()
    assert receipt['setup_args_sha256']==hashlib.sha256(fresh.args_bytes(args+['--',*command])).hexdigest()


def test_smoke_uses_exact_shared_bootstrap():
    source=SOURCE.read_text()
    assert "entry=wrapper.namespace_command(command,prepared['outer_namespaces'])" in source
    assert "rmdir(" not in source and "unlink(" not in source
