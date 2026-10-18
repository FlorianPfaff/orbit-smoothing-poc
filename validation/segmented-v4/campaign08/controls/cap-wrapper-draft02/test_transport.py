from pathlib import Path
import fcntl, hashlib, importlib.util, json, os
import pytest
from test_wrapper import fixture, m, write

class ExecBoundary(Exception):
    pass

@pytest.mark.parametrize('command', [None, ['/exact executable', '--', '--args', 'literal value']])
def test_main_seals_only_setup_and_execs_exact_command(fixture, tmp_path, monkeypatch, capsys, command):
    p, mount, files, cfg, inner, fresh, probe = fixture
    s=importlib.util.spec_from_file_location('real_planner', Path(__file__).with_name('plan_segmented_fit_namespace01.py'))
    planner=importlib.util.module_from_spec(s);s.loader.exec_module(planner)
    fresh.sealed_args_fd=planner.sealed_args_fd;fresh.args_bytes=planner.args_bytes
    expected=m.prepare(p,fresh,None,probe)
    if command is not None:
        expected['command']=command
        monkeypatch.setattr(m,'prepare',lambda *a:expected)
    monkeypatch.setattr(m,'module',lambda name,path: fresh if name=='reviewed_fresh_fit_mount_planner' else probe)
    seen={}
    monkeypatch.setattr(m,'descriptor_boundary',lambda fd:seen.update(boundary_fd=fd))
    def execve(binary,argv,env):
        fd=int(argv[2]); seen.update(binary=binary,argv=argv,env=env,fd=fd)
        seen['sealed']=os.read(fd,1000000)
        assert fcntl.fcntl(fd,1034)==15
        raise ExecBoundary()
    monkeypatch.setattr(m.os,'execve',execve)
    invocation=write(tmp_path/'invocation.json',p)
    with pytest.raises(ExecBoundary):m.main(['--invocation',invocation['path'],'--sha256',invocation['sha256']])
    assert seen['boundary_fd']==seen['fd']
    assert seen['argv']==[p['bubblewrap']['path'],'--args',str(seen['fd']),'--',*expected['command']]
    assert seen['env']=={} and seen['binary']==p['bubblewrap']['path']
    assert seen['sealed']==planner.args_bytes(expected['mount_args'])
    receipt=json.loads(capsys.readouterr().out)
    assert receipt['setup_args_sha256']==hashlib.sha256(seen['sealed']+planner.args_bytes(['--',*expected['command']])).hexdigest()
    assert receipt['sealed_options_sha256']==hashlib.sha256(seen['sealed']).hexdigest()
    assert receipt['argument_transport']=='sealed_setup_fd_with_direct_command_argv'
    with pytest.raises(OSError):os.fstat(seen['fd'])


def test_transport_change_does_not_change_prepare_or_descriptor_logic():
    import ast
    old=Path('/mnt/d/orbit-segmented-v4/control/cap-wrapper-draft01/with_segmented_fit_namespace02.py')
    def functions(path):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef)}
    before=functions(old);after=functions(Path(m.__file__))
    assert before.keys()==after.keys()
    assert all(before[k]==after[k] for k in before if k!='main')
