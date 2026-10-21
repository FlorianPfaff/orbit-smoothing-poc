"""Fabricated D01 orchestration tests. No native processes, builds or SSH."""
import contextlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest

HERE = Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE/(name+'.py'))
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


r = load('run_row_trace_d01')
b = load('build_row_trace_d01')


def write(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return r.artifact(path)


class Owned:
    def __init__(self):
        self.running = True;self.calls = [];self.last_cleanup = None
        self.fail_final_cleanup = False
        self.child = types.SimpleNamespace(poll=lambda:None if self.running else 0)
    def cleanup(self, force):
        self.calls.append(force);self.running = False
        if self.fail_final_cleanup and len(self.calls)>1:
            self.last_cleanup={'verified':False};raise RuntimeError('Fabricated final cleanup failure')
        self.last_cleanup = {'verified':True, 'forced':force}


class Driver:
    def __init__(self, execution):
        self.execution = execution;self.calls = [];self.owned = [];self.mode = 'ok'
        self.source = {'sha256':'frozen', 'files':{'test':'sha'}}
        self.save_calls = 0;self.fail_save_at = None;self.after = None
    def load_execution(self, path):return self.execution
    def source_receipt(self, path):return self.source
    def resolved_host_path(self, path, execution):return Path(path)
    def admission(self, *args):
        if self.mode == 'conflict':raise RuntimeError('Competing workload')
        return {'status':'admitted'}
    def stamp(self):return '2026-10-15T12:00:00Z'
    def interrupted(self, *args):raise KeyboardInterrupt('signal')
    cleanup_signals = staticmethod(contextlib.nullcontext)
    def save(self, path, value):
        self.save_calls += 1
        if self.save_calls == self.fail_save_at or (self.mode == 'final_save' and value.get('final_cleanup')):
            raise OSError('Fabricated receipt write failure')
        write(path, value)
    def supervise(self, argv, **kwargs):
        self.calls.append((list(map(str,argv)), kwargs));owned = Owned();self.owned.append(owned)
        owned.fail_final_cleanup=self.mode=='cleanup_failure'
        kwargs['registry'].append(owned)
        try:
            kwargs['on_started'](77);kwargs['guard_live']()
            if self.mode == 'timeout':raise subprocess.TimeoutExpired(argv, kwargs['limit'])
            if self.mode == 'interrupt':raise KeyboardInterrupt('Fabricated interrupt')
            if self.mode == 'clone_failed':return 1
            if any(str(x).endswith('build_row_trace_d01.py') for x in argv):
                p=Path(self.execution['paths']['build']);write(p/'groops','fake native');write(p/'build-manifest.json',{'executable_sha256':r.sha(p/'groops')})
            if self.after:self.after()
            owned.running = False
            return 1 if any(str(x).endswith('validate_numerics_nuisance.py') for x in argv) else 0
        finally:
            owned.cleanup(force=owned.running)
            kwargs['on_finished']({'cleanup':owned.last_cleanup, 'elapsed_seconds':0.01})


@pytest.fixture
def context(tmp_path, monkeypatch):
    root=tmp_path/'diagnostic';root.mkdir();prior=tmp_path/'prior06';(prior/'control').mkdir(parents=True)
    paths={k:str(root/k) for k in ['control','source','native_source','build','binaries','run','temporary','upstream_repository','prefix']}
    for key in ['control','source','upstream_repository','prefix']:Path(paths[key]).mkdir()
    paths.update(python=str(root/'python'),cmake=str(root/'cmake'),wrapper=str(root/'control/with_correctness_namespace_04.py'))
    runtime=write(root/'python','fake interpreter');write(root/'cmake','fake cmake');write(paths['wrapper'],'# wrapper')
    e={'paths':paths,'runtime_artifacts':{'control_python':runtime}}
    ep=write(root/'control/execution.json',e);d=Driver(e)
    helperpins={name:write(root/'control'/filename,'# helper') for name,filename in {'build':'build_row_trace_d01.py','install':'install_row_trace.py','header':'rowArithmeticTrace.h','compare':'verify_trace_equivalence.py'}.items()}
    helperpins['wrapper']=r.artifact(paths['wrapper'])
    profile=write(prior/'validation-06/objective-log_drag_ou/point-001-nonzero-full-prior/profile.xml','profile')
    plan={'schema':'orbit-poc-diagnostic-row-trace-plan-v1','runner':r.artifact(r.__file__),'execution':ep,
          'driver':write(prior/'control/validate_candidate_06.py','# fake driver'),
          'source_freeze':write(prior/'control/candidate06-source-freeze.json',{'source':d.source}),
          'helpers':helperpins,'inputs':{'profile':profile},'input_links':{},
          'prior_pipeline':write(prior/'validation-06/pipeline.json',{'status':'failed','final_cleanup':{'verified':True}}),
          'last_generation':8}
    planpath=root/'control/plan.json';write(planpath,plan)
    loader=types.SimpleNamespace(exec_module=lambda module:None)
    monkeypatch.setattr(r,'importlib',types.SimpleNamespace(util=types.SimpleNamespace(
        spec_from_file_location=lambda *args:types.SimpleNamespace(loader=loader),module_from_spec=lambda spec:d)))
    handlers={2:'original-int',15:'original-term'}
    signals=types.SimpleNamespace(SIGINT=2,SIGTERM=15,getsignal=lambda n:handlers[n],signal=lambda n,v:handlers.__setitem__(n,v))
    monkeypatch.setattr(r,'signal',signals)
    def invoke():
        monkeypatch.setattr(sys,'argv',['run_row_trace_d01.py','--plan',str(planpath),'--sha256',r.sha(planpath)])
        return r.main()
    return types.SimpleNamespace(root=root,plan=plan,planpath=planpath,driver=d,paths=paths,invoke=invoke,handlers=handlers)


def result(c):return json.loads((Path(c.paths['run'])/'pipeline.json').read_text())


def test_complete_diagnostic_keeps_failed_replays_and_no_acceptance(context,monkeypatch):
    c=context;monkeypatch.setenv('ORBIT_POC_ROW_TRACE_DIRECTORY','unrelated')
    c.invoke();j=result(c)
    assert j['status']=='completed' and j['scientific_correctness_resolved'] is False
    assert [v['name'] for v in j['steps']]==['clone','checkout','build','trace-off','trace-on','equivalence']
    assert [v['returncode'] for v in j['steps'][3:5]]==[1,1]
    assert all(v['finished_at'] and v['cleanup']['verified'] for v in j['steps'])
    assert j['final_cleanup']['verified'] and all(not v.running and len(v.calls)==2 for v in c.driver.owned)
    assert c.handlers=={2:'original-int',15:'original-term'}
    assert all('ORBIT_POC_ROW_TRACE_DIRECTORY' not in kwargs['env'] for _,kwargs in c.driver.calls)
    assert any(x.startswith('ORBIT_POC_ROW_TRACE_DIRECTORY=') for x in c.driver.calls[4][0])
    assert not any(x.startswith('ORBIT_POC_ROW_TRACE_DIRECTORY=') for x in c.driver.calls[3][0])
    with pytest.raises(RuntimeError,match='exists'):c.invoke()


@pytest.mark.parametrize('mode,error',[('clone_failed',RuntimeError),('timeout',subprocess.TimeoutExpired),('interrupt',KeyboardInterrupt)])
def test_failed_or_interrupted_step_is_terminal_and_owned_cleanup_runs(context,mode,error):
    c=context;c.driver.mode=mode
    with pytest.raises(error):c.invoke()
    j=result(c);assert j['status']=='failed' and j['finished_at'] and j['final_cleanup']['verified']
    assert len(j['steps'])==1 and j['steps'][0]['status']!='running' and j['steps'][0]['finished_at']
    assert all(not v.running for v in c.driver.owned) and c.handlers=={2:'original-int',15:'original-term'}


@pytest.mark.parametrize('save_call',[2,3,4])
def test_transient_step_receipt_failure_preserves_terminal_failure(context,save_call):
    c=context;c.driver.fail_save_at=save_call
    with pytest.raises(OSError):c.invoke()
    j=result(c);assert j['status']=='failed' and j['final_cleanup']['verified']
    assert j['steps'][0]['status']!='running' and j['steps'][0]['finished_at']
    assert all(not v.running for v in c.driver.owned) and c.handlers=={2:'original-int',15:'original-term'}


def test_final_save_failure_still_restores_handlers_and_cleans_children(context):
    c=context;c.driver.mode='final_save'
    with pytest.raises(OSError):c.invoke()
    assert all(not v.running for v in c.driver.owned) and c.handlers=={2:'original-int',15:'original-term'}


def test_unverified_final_cleanup_cannot_claim_completed(context):
    c=context;c.driver.mode='cleanup_failure';c.invoke();j=result(c)
    assert j['status']=='failed' and not j['final_cleanup']['verified'] and j['final_cleanup']['errors']
    assert c.handlers=={2:'original-int',15:'original-term'} and j['scientific_correctness_resolved'] is False


@pytest.mark.parametrize('which',['input','helper','source','runtime','unclean','conflict','link'])
def test_identity_or_admission_failure_prevents_native_work(context,which):
    c=context
    if which=='input':Path(c.plan['inputs']['profile']['path']).write_text('tampered')
    elif which=='helper':Path(c.plan['helpers']['install']['path']).write_text('tampered')
    elif which=='source':c.driver.source={'sha256':'wrong','files':{}}
    elif which=='runtime':Path(c.paths['python']).write_text('tampered')
    elif which=='unclean':
        c.plan['prior_pipeline']=write(c.plan['prior_pipeline']['path'],{'status':'failed','final_cleanup':{'verified':False}});write(c.planpath,c.plan)
    elif which=='link':
        link=c.root/'observations';target=c.root/'original';write(target,'same bytes');link.symlink_to(target)
        c.plan['input_links']={str(link):str(target)};write(c.planpath,c.plan)
        changed=c.root/'replacement';write(changed,'same bytes');link.unlink();link.symlink_to(changed)
    else:c.driver.mode='conflict'
    with pytest.raises(RuntimeError):c.invoke()
    assert not c.driver.calls and not Path(c.paths['run']).exists()


def test_input_mutation_after_a_step_is_preserved_as_global_failure(context):
    c=context;c.driver.after=lambda:Path(c.plan['inputs']['profile']['path']).write_text('changed during command')
    with pytest.raises(RuntimeError,match='Pin changed'):c.invoke()
    j=result(c);assert j['status']=='failed' and len(j['steps'])==1 and j['final_cleanup']['verified']


@pytest.mark.parametrize('which',['revision','changed_source','help_failure'])
def test_build_refuses_wrong_identity_changed_inputs_or_failed_startup(tmp_path,monkeypatch,which):
    source=tmp_path/'native';build=tmp_path/'build';(source/'source').mkdir(parents=True);build.mkdir()
    write(source/'source/a.cpp','original');write(source/'orbit-poc-extension.json',{});write(build/'groops','fake');write(build/'CMakeCache.txt','cache')
    calls=[]
    def check_output(argv,**kwargs):
        if 'rev-parse' in argv:return 'wrong' if which=='revision' else b.COMMIT
        return 'fabricated tool version'
    def run(argv,**kwargs):
        argv=list(map(str,argv));calls.append(argv)
        if '--build' in argv and which=='changed_source':write(source/'source/a.cpp','changed')
        if '--help' in argv and which=='help_failure':raise subprocess.CalledProcessError(1,argv)
    monkeypatch.setattr(b.subprocess,'check_output',check_output);monkeypatch.setattr(b,'run',run)
    monkeypatch.setattr(sys,'argv',['build','--source-dir',str(source),'--build-dir',str(build),'--numerics'])
    with pytest.raises((ValueError,RuntimeError,subprocess.CalledProcessError)):b.main()
    assert not (build/'build-manifest.json').exists()
    if which=='revision':assert not calls


def test_prepare_pins_all_inputs_and_rejects_modified_build_adapter(tmp_path):
    # Only the two absolute deployment roots are remapped for this fixture.
    original=HERE/'original_build_groops.py'
    source_text=original.read_text()
    D=tmp_path/'D';R=tmp_path/'R';(D/'control').mkdir(parents=True);(R/'control').mkdir(parents=True)
    write(D/'source/scripts/build_groops.py',source_text)
    write(D/'control/diagnostic-execution.json',{'paths':{k:str(D/k) for k in ['native_source','build','binaries','run','temporary']}})
    adapted=(HERE/'build_row_trace_d01.py').read_text().replace('@DIAGNOSTIC_D01_ROOT@',str(D))
    write(D/'control/build_row_trace_d01.py',adapted)
    for n in ['run_row_trace_d01.py','install_row_trace.py','verify_trace_equivalence.py','rowArithmeticTrace.h','with_correctness_namespace_04.py']:write(D/'control'/n,'# fixture')
    write(R/'control/validate_candidate_06.py','from pathlib import Path\ndef resolved_host_path(path,execution): return Path(path).resolve()\n')
    write(R/'control/candidate06-source-freeze.json','{}')
    point=R/'validation-06/objective-log_drag_ou/point-001-nonzero-full-prior'
    for n in ['profile.xml','closure-03/variational.dat','closure-03/reference.txt','native/log_density.txt','native/data/observations.dat']:write(point/n,'original '+n)
    target=R/'target-observations.dat';write(target,'original linked observations');(point/'native/data/linked.dat').symlink_to(target)
    write(R/'validation-06/pipeline.json',{})
    text=(HERE/'prepare_row_trace_d01.py').read_text().replace('@DIAGNOSTIC_D01_ROOT@',str(D)).replace('@RECOVERY06_ROOT@',str(R))
    exec(compile(text,'prepare_fixture','exec'),{})
    plan=json.loads((D/'control/plan.json').read_text());assert len(plan['inputs'])==6
    assert plan['input_links']=={str(point/'native/data/linked.dat'):str(target)}
    for pin in plan['inputs'].values():assert r.sha(pin['path'])==pin['sha256']
    with pytest.raises(AssertionError):exec(compile(text,'prepare_fixture','exec'),{})
    (D/'control/plan.json').unlink();write(D/'control/build_row_trace_d01.py',adapted+'\n# unsupported change\n')
    with pytest.raises(AssertionError):exec(compile(text,'prepare_fixture','exec'),{})
    assert not (D/'control/plan.json').exists()
