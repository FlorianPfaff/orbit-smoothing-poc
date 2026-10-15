"""Fabricated D03 orchestration tests. No native processes, builds or SSH."""
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


r = load('run_row_trace_d03')
b = load('build_row_trace_d03')


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
    def collect_inputs(self,profile,execution,driver):return self.identity_plan['inputs'],self.identity_plan['input_links'],{'fake':True}
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
            if any(str(x).endswith('build_row_trace_d03.py') for x in argv):
                p=Path(self.execution['paths']['build']);write(p/'groops','fake native');write(p/'build-manifest.json',{'executable_sha256':r.sha(p/'groops')})
            if any(str(x).endswith('validate_numerics_nuisance.py') for x in argv):
                folder=Path(argv[argv.index('--output')+1]);folder.mkdir()
                write(folder/'qr.diagnostic-incomplete.json',{'schema':'orbit-poc-d03-generation-stop-v1','diagnostic_only':True,'scientific_complete':False,'completed_generations':4})
                for generation in range(1,5):
                    for suffix in ('factor.json','profile.json','nuisance_line_search.json'):write(folder/f'qr.{generation}.{suffix}',{})
                write(folder/'receipt.json',{'passed':False,'returncode':1,'timed_out':False,'profile':None})
            if self.after:self.after()
            owned.running = False
            return 1 if any(str(x).endswith('validate_numerics_nuisance.py') for x in argv) else 0
        finally:
            owned.cleanup(force=owned.running)
            kwargs['on_finished']({'cleanup':owned.last_cleanup, 'elapsed_seconds':0.01})


@pytest.fixture
def context(tmp_path, monkeypatch):
    root=tmp_path/'diagnostic';root.mkdir();prior=tmp_path/'prior08';(prior/'control').mkdir(parents=True)
    paths={k:str(root/k) for k in ['control','source','native_source','build','binaries','run','temporary','upstream_repository','prefix']}
    for key in ['control','source','upstream_repository','prefix']:Path(paths[key]).mkdir()
    paths.update(python=str(root/'python'),cmake=str(root/'cmake'),wrapper=str(root/'control/with_correctness_namespace_04.py'))
    runtime=write(root/'python','fake interpreter');write(root/'cmake','fake cmake');write(paths['wrapper'],'# wrapper')
    e={'paths':paths,'runtime_artifacts':{'control_python':runtime}}
    ep=write(root/'control/execution.json',e);d=Driver(e)
    helperpins={name:write(root/'control'/filename,'# helper') for name,filename in {'build':'build_row_trace_d03.py','install':'install_row_trace.py','header':'nuisanceArithmeticTrace.h','compare':'verify_trace_equivalence.py'}.items()}
    helperpins['wrapper']=r.artifact(paths['wrapper'])
    helperpins['prepare']=write(root/'control/prepare_row_trace_d03.py','# input identity helper')
    helperpins['input_identity']=write(root/'control/input-identity.json',{'fake':True})
    profile=write(prior/'validation-07/objective-log_drag_ou/point-006-direction-1.0-1-repeat/profile.xml','profile')
    plan={'schema':'orbit-poc-diagnostic-row-trace-plan-v2','runner':r.artifact(r.__file__),'execution':ep,
          'driver':write(prior/'control/validate_candidate_07.py','# fake driver'),
          'source_freeze':write(prior/'control/candidate07-source-freeze.json',{'source':d.source}),
          'helpers':helperpins,'inputs':{'profile':profile},'input_links':{},
          'prior_pipeline':write(prior/'validation-07/pipeline.json',{'status':'failed','final_cleanup':{'verified':True}}),
          'last_generation':4}
    plan['prior_postprocess']=write(prior/'postprocess-07-01/pipeline.json',{'status':'failed','finished_at':'terminal','steps':[{'cleanup_verified':True}], 'validation_pipeline':plan['prior_pipeline']})
    d.identity_plan=plan
    planpath=root/'control/plan.json';write(planpath,plan)
    loader=types.SimpleNamespace(exec_module=lambda module:None)
    monkeypatch.setattr(r,'importlib',types.SimpleNamespace(util=types.SimpleNamespace(
        spec_from_file_location=lambda *args:types.SimpleNamespace(loader=loader),module_from_spec=lambda spec:d)))
    handlers={2:'original-int',15:'original-term'}
    signals=types.SimpleNamespace(SIGINT=2,SIGTERM=15,getsignal=lambda n:handlers[n],signal=lambda n,v:handlers.__setitem__(n,v))
    monkeypatch.setattr(r,'signal',signals)
    def invoke():
        monkeypatch.setattr(sys,'argv',['run_row_trace_d03.py','--plan',str(planpath),'--sha256',r.sha(planpath)])
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
    assert any(x.startswith('ORBIT_POC_D03_DIRECTORY=') for x in c.driver.calls[4][0])
    assert not any(x.startswith('ORBIT_POC_D03_DIRECTORY=') for x in c.driver.calls[3][0])
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


@pytest.mark.parametrize('bad',['running','unclean','wrong_run'])
def test_requires_original_postprocess_terminal_and_exact_validation(context,bad):
    c=context;p=Path(c.plan['prior_postprocess']['path']);v=json.loads(p.read_text())
    if bad=='running':v['status']='running'
    if bad=='unclean':v['steps'][0]['cleanup_verified']=False
    if bad=='wrong_run':v['validation_pipeline']={'sha256':'f'*64}
    c.plan['prior_postprocess']=write(p,v);write(c.planpath,c.plan)
    with pytest.raises(RuntimeError):c.invoke()
    assert not c.driver.calls

@pytest.mark.parametrize('bad',['missing_sentinel','wrong_limit','complete','profile_present','fifth_generation','timeout','passed_replay','unexpected_native_error'])
def test_requires_explicit_incomplete_diagnostic_boundary(tmp_path,bad):
    folder=tmp_path/'replay';folder.mkdir()
    sentinel={'schema':'orbit-poc-d03-generation-stop-v1','diagnostic_only':True,'scientific_complete':False,'completed_generations':4}
    receipt={'passed':False,'returncode':1,'timed_out':False,'profile':None}
    if bad=='wrong_limit':sentinel['completed_generations']=5
    if bad=='complete':sentinel['scientific_complete']=True
    if bad!='missing_sentinel':write(folder/'qr.diagnostic-incomplete.json',sentinel)
    if bad=='profile_present':write(folder/'qr.profile.json',{'nuisance_converged':True})
    if bad=='timeout':receipt['timed_out']=True
    if bad=='passed_replay':receipt['passed']=True
    if bad=='unexpected_native_error':receipt['returncode']=139
    for generation in range(1,6 if bad=='fifth_generation' else 5):
        for suffix in ('factor.json','profile.json','nuisance_line_search.json'):write(folder/f'qr.{generation}.{suffix}',{})
    write(folder/'receipt.json',receipt)
    with pytest.raises((RuntimeError,FileNotFoundError)):r.check_diagnostic_boundary(folder)

@pytest.mark.parametrize('bad',[None,'running','unclean_post','wrong_post_run','changed_build','changed_source','unknown_variable','missing_input'])
def test_prepare_uses_xml_closure_and_all_metadata_without_rewriting_profile(tmp_path,monkeypatch,bad):
    p=load('prepare_row_trace_d03');D=tmp_path/'D';R=tmp_path/'R'
    monkeypatch.setattr(p,'D',D);monkeypatch.setattr(p,'R',R)
    (D/'control').mkdir(parents=True);(R/'control').mkdir(parents=True)
    source_text=(HERE/'original_build_groops.py').read_text()
    write(D/'source/scripts/build_groops.py',source_text)
    adapted=(HERE/'build_row_trace_d03.py').read_text().replace('@REMOTE_DATA_ROOT@/orbit-v31-diagnostic-row-trace-03-PRIVATE_USER',str(D))
    if bad=='changed_build':adapted+='\n# unapproved modification\n'
    write(D/'control/build_row_trace_d03.py',adapted)
    for name in ('run_row_trace_d03.py','prepare_row_trace_d03.py','install_row_trace.py','verify_trace_equivalence.py','nuisanceArithmeticTrace.h','with_correctness_namespace_04.py'):write(D/'control'/name,'# fixture')
    write(D/'control/diagnostic-execution.json',{'paths':{key:str(D/key) for key in ('native_source','build','binaries','run','temporary')}})
    write(R/'control/validate_candidate_07.py','from pathlib import Path\ndef load_execution(p):return {}\ndef source_receipt(p):return {"sha256":"frozen"}\ndef host_path(p,e):return Path(p)\ndef resolved_host_path(p,e):return Path(p).resolve()\n')
    write(R/'control/candidate07-source-freeze.json',{'source':{'sha256':'changed' if bad=='changed_source' else 'frozen'}})
    prior=write(R/'validation-07/pipeline.json',{'status':'running' if bad=='running' else 'failed','finished_at':'done','final_cleanup':{'verified':True}})
    write(R/'postprocess-07-01/pipeline.json',{'status':'failed','finished_at':'done','steps':[{'cleanup_verified':bad!='unclean_post'}],'validation_pipeline':{'sha256':'wrong' if bad=='wrong_post_run' else prior['sha256']}})
    point=R/'validation-07/objective-log_drag_ou/point-006-direction-1.0-1-repeat'
    for name in ('closure-02/variational.dat','closure-02/reference.txt','native/log_density.txt','metadata/G01.dat','metadata/G02.dat'):write(point/name,'exact '+name)
    target=point/'real.dat';write(target,'data');(point/'linked.dat').symlink_to(target)
    variable='{unexpected}' if bad=='unknown_variable' else '{prn}'
    xml=f'<groops><inputfileVariational>{point}/closure-02/variational.dat</inputfileVariational><inputfileNumericsReferenceParameters>{point}/closure-02/reference.txt</inputfileNumericsReferenceParameters><inputfileLogDensity>{point}/native/log_density.txt</inputfileLogDensity><inputfileOrbit>{point}/metadata/{variable}.dat</inputfileOrbit><inputfileObservations>{point}/linked.dat</inputfileObservations></groops>'
    write(point/'profile.xml',xml)
    if bad=='missing_input':(point/'closure-02/reference.txt').unlink()
    if bad is not None:
        with pytest.raises(RuntimeError):p.main()
        assert not (D/'control/plan.json').exists()
    else:
        p.main();v=json.loads((D/'control/plan.json').read_text())
        assert len(v['inputs'])==7 and v['last_generation']==4
        assert v['input_links']=={str(point/'linked.dat'):str(target)}
        identity=json.loads((D/'control/input-identity.json').read_text())
        assert len(identity['inputs'])==5 and all('closure-03' not in row['declared'] for row in identity['inputs'])
        assert (point/'profile.xml').read_text()==xml
        with pytest.raises(RuntimeError,match='retry'):p.main()


def test_input_closure_captures_parent_links_and_exact_glob_support(tmp_path):
    p=load('prepare_row_trace_d03');folder=tmp_path/'source';folder.mkdir()
    write(folder/'G01.dat','one');alias=tmp_path/'alias';alias.symlink_to(folder,target_is_directory=True)
    profile=tmp_path/'profile.xml';write(profile,f'<groops><inputfileOrbit>{alias}/{{prn}}.dat</inputfileOrbit></groops>')
    driver=types.SimpleNamespace(host_path=lambda path,e:Path(path),resolved_host_path=lambda path,e:Path(path).resolve())
    first=p.collect_inputs(profile,{},driver)
    assert first[1]=={str(alias):str(folder)}
    write(folder/'G02.dat','two');second=p.collect_inputs(profile,{},driver);assert first!=second
    other=tmp_path/'replacement';other.mkdir();write(other/'G01.dat','one');alias.unlink();alias.symlink_to(other,target_is_directory=True)
    third=p.collect_inputs(profile,{},driver);assert first[1]!=third[1] and first[2]!=third[2]


def test_alias_aware_glob_maps_absolute_directory_link_before_expansion(tmp_path):
    p=load('prepare_row_trace_d03');staged=tmp_path/'staged';staged.mkdir();files=tmp_path/'files';files.mkdir()
    write(files/'G01.dat','exact');(staged/'directory').symlink_to('/canonical-data',target_is_directory=True)
    def mapped(path,e):
        path=Path(path)
        for logical,physical in [(Path('/canonical-data'),files),(Path('/canonical-root'),staged)]:
            if path==logical or logical in path.parents:return physical/path.relative_to(logical)
        return path
    driver=types.SimpleNamespace(host_path=mapped,resolved_host_path=lambda path,e:Path(path).resolve())
    profile=tmp_path/'profile.xml';write(profile,'<groops><inputfileOrbit>/canonical-root/directory/{prn}.dat</inputfileOrbit></groops>')
    inputs,links,identity=p.collect_inputs(profile,{},driver)
    assert len(inputs)==2 and links=={str(staged/'directory'):'/canonical-data'}
    assert identity['inputs'][0]['files'][0]['resolved']['path']==str(files/'G01.dat')
