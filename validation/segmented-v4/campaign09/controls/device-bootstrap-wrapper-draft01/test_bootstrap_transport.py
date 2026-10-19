from pathlib import Path
import ast,fcntl,hashlib,importlib.util,json,os
import pytest
from test_wrapper import fixture,m,write

class ExecBoundary(Exception):pass

@pytest.mark.parametrize('tail',[None,['literal value','--','--args','-c','$(not executed)']])
def test_actual_transport_wraps_only_command(fixture,tmp_path,monkeypatch,capsys,tail):
 p,mount,files,cfg,inner,fresh,probe=fixture
 s=importlib.util.spec_from_file_location('real_planner',Path(__file__).with_name('plan_segmented_fit_namespace01.py'));planner=importlib.util.module_from_spec(s);s.loader.exec_module(planner)
 fresh.sealed_args_fd=planner.sealed_args_fd;fresh.args_bytes=planner.args_bytes
 expected=m.prepare(p,fresh,None,probe)
 if tail is not None:expected['command']=expected['command'][:6]+tail
 monkeypatch.setattr(m,'prepare',lambda *a:expected)
 monkeypatch.setattr(m,'module',lambda name,path:fresh if name=='reviewed_fresh_fit_mount_planner' else probe)
 seen={};monkeypatch.setattr(m,'descriptor_boundary',lambda fd:seen.update(boundary_fd=fd))
 def execve(binary,argv,env):
  fd=int(argv[2]);seen.update(binary=binary,argv=argv,env=env,fd=fd,sealed=os.read(fd,1000000));assert fcntl.fcntl(fd,1034)==15;raise ExecBoundary()
 monkeypatch.setattr(m.os,'execve',execve);invocation=write(tmp_path/'invocation.json',p)
 with pytest.raises(ExecBoundary):m.main(['--invocation',invocation['path'],'--sha256',invocation['sha256']])
 entry=m.namespace_command(expected['command'],expected['outer_namespaces'])
 assert seen['argv']==[p['bubblewrap']['path'],'--args',str(seen['fd']),'--',*entry]
 assert entry[:6]==expected['command'][:5]+['-c'] and entry[10:]==expected['command']
 assert seen['sealed']==planner.args_bytes(expected['mount_args']) and seen['env']=={} and seen['boundary_fd']==seen['fd']
 receipt=json.loads(capsys.readouterr().out)
 assert receipt['command']==expected['command'] and receipt['entry_command']==entry
 assert receipt['setup_args_sha256']==hashlib.sha256(planner.args_bytes(expected['mount_args']+['--',*expected['command']])).hexdigest()
 assert receipt['entry_args_sha256']==hashlib.sha256(planner.args_bytes(expected['mount_args']+['--',*entry])).hexdigest()
 assert receipt['sealed_options_sha256']==hashlib.sha256(seen['sealed']).hexdigest() and receipt['bootstrap_sha256']==m.BOOTSTRAP_SHA256
 with pytest.raises(OSError):os.fstat(seen['fd'])

@pytest.mark.parametrize('kind',['short','string','nonstring','nul','taskset','cpu','relative_python','no_B','incomplete_namespace'])
def test_invalid_command_entry_rejected(kind):
 command=['/usr/bin/taskset','-c','24','/frozen/python','-B','/original.py'];outer={k:k+':[1]' for k in ('mnt','pid','net')}
 if kind=='short':command=command[:5]
 elif kind=='string':command='bad'
 elif kind=='nonstring':command[-1]=None
 elif kind=='nul':command[-1]='bad\0'
 elif kind=='taskset':command[0]='/other'
 elif kind=='cpu':command[2]='32'
 elif kind=='relative_python':command[3]='python'
 elif kind=='no_B':command[4]='-c'
 else:outer.pop('mnt')
 with pytest.raises(RuntimeError):m.namespace_command(command,outer)

def test_only_shared_entry_and_prepare_metadata_added():
 old=Path('/mnt/d/orbit-segmented-v4/control/loader-alias-wrapper-draft01/with_segmented_fit_namespace04.py')
 def functions(p):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(p.read_text()).body if isinstance(n,ast.FunctionDef)}
 before=functions(old);after=functions(Path(m.__file__))
 assert set(after)==set(before)|{'namespace_command'}
 assert all(before[k]==after[k] for k in before if k not in {'main','prepare'})
 assert m.BOOTSTRAP_CODE==Path(__file__).with_name('bootstrap.py.txt').read_text()
 assert m.BOOTSTRAP_SHA256==hashlib.sha256(m.BOOTSTRAP_CODE.encode()).hexdigest()
 compile(m.BOOTSTRAP_CODE,'bootstrap','exec')

def test_prepare_tracks_actual_outer_namespaces(fixture):
 p,*_,fresh,probe=fixture
 assert m.prepare(p,fresh,None,probe)['outer_namespaces']=={k:os.readlink('/proc/self/ns/'+k) for k in ('mnt','pid','net')}
