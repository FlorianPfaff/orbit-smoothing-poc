"""Fabricated supplemental lifecycle tests; no native build, fit or SSH."""
import contextlib
import fcntl
import importlib.util
import json
from pathlib import Path
import subprocess
import types

import pytest

spec=importlib.util.spec_from_file_location('supplemental06',Path(__file__).with_name('supplemental_point017_06.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data));return r.artifact(path)


class Owned:
    def __init__(self,fail=False):
        self.running=True;self.calls=[];self.fail=fail;self.last_cleanup=None
        self.child=types.SimpleNamespace(poll=lambda:None if self.running else 0)
    def cleanup(self,force):
        self.calls.append(force)
        if self.fail:
            self.last_cleanup={'verified':False};raise RuntimeError('fabricated cleanup failure')
        self.running=False;self.last_cleanup={'verified':True,'forced':force};return self.last_cleanup


class Driver:
    def __init__(self):
        self.calls=[];self.save_calls=0;self.mode='strict';self.source={'sha256':'s'*64};self.after=None
        self.owned=None;self.fail_save_at=None
    def admission(self,*args):
        if self.mode=='conflict':raise RuntimeError('competing native workload')
        return {'status':'admitted','conflicting_processes':[]}
    def verify_pins(self,*args):return self.source
    def stamp(self):return '2026-10-15T12:00:00Z'
    def interrupted(self,*args):raise KeyboardInterrupt('fabricated interruption')
    cleanup_signals=staticmethod(contextlib.nullcontext)
    def save(self,path,data):
        self.save_calls+=1
        if self.save_calls==self.fail_save_at:raise OSError('fabricated receipt failure')
        write(path,data)
    def supervise(self,argv,**kwargs):
        self.calls.append((argv,kwargs));self.owned=Owned(fail=self.mode=='cleanup_failure');kwargs['registry'].append(self.owned)
        try:
            kwargs['on_started'](77);kwargs['guard_live']()
            if self.mode=='timeout':raise subprocess.TimeoutExpired(argv,7500)
            if self.mode=='interrupt':raise KeyboardInterrupt('fabricated signal')
            if self.mode!='missing':
                plan=self.context['plan'];out=self.context['output']/'replay'
                result={'schema':'orbit-poc-native-nuisance-validation-v1','native_sha256':plan['native']['sha256'],
                    'source_profile':plan['input_artifacts']['profile']['path'],
                    'source_profile_sha256':plan['input_artifacts']['profile']['sha256'],
                    'passed':self.mode not in ('failed','cleanup_failure'),
                    'strict_nuisance_converged':self.mode=='strict','progress_only_floor_validated':self.mode=='floor'}
                if self.mode=='wrong_source':result['source_profile_sha256']='0'*64
                write(out/'receipt.json',result)
            if self.after:self.after()
            self.owned.running=False
            return 1 if self.mode=='failed' else 0
        finally:
            self.owned.cleanup(force=self.owned.running)
            kwargs['on_finished']({'cleanup':self.owned.last_cleanup,'elapsed_seconds':0.01})


@pytest.fixture
def fixture(tmp_path):
    paths={k:str(tmp_path/k) for k in ('control','source','binaries','temporary','run')};paths['root']=str(tmp_path)
    paths.update(python='/scientific/python',wrapper=str(tmp_path/'control/with_correctness_namespace_04.py'))
    for k in ('control','source','binaries','temporary','run'):Path(paths[k]).mkdir()
    e={'paths':paths,'fit_cpu':24,'runtime_artifacts':{'control_python':{'path':'/usr/bin/python3'}}}
    ep=write(tmp_path/'control/execution.json',e);pp=write(tmp_path/'control/pins.json',{'source_sha256':'s'*64})
    old=tmp_path/'prior05/validation-05/objective-log_drag_ou/point-017-direction-0.125-1'
    inputs={name:write(old/(name+'.json'),{'role':name}) for name in r.INPUT_ROLES}
    binary=tmp_path/'binaries/bin';binary.write_text('fake executable');native={'sha256':r.sha(binary)}
    final=tmp_path/'binaries'/('groops-'+native['sha256'][:16]);binary.rename(final);native['path']=str(final)
    native['build_manifest_sha256']=write(Path(str(final)+'.build-manifest.json'),{'executable_sha256':native['sha256']})['sha256']
    pipe={'status':'failed','finished_at':'done','final_cleanup':{'verified':True},'required_pins':pp,'execution':ep,
          'source':{'sha256':'s'*64},'native':native,'resume':{'status':'not_applicable','reason':'no_campaign_running'},
          'steps':[{'name':n,'status':'failed','finished_at':'done','cleanup':{'verified':True}} for n in r.REQUIRED_STEPS]}
    vp=write(tmp_path/'run/pipeline.json',pipe)
    postroot=tmp_path/'postprocess-06-01'
    postplan={'schema':'orbit-poc-correctness-postprocess06-plan-v1','output_root':str(postroot),'execution':ep,
              'candidate_pins':pp,'source_sha256':'s'*64}
    postplanpin=write(tmp_path/'control/postprocess-plan.json',postplan)
    post={'status':'failed','finished_at':'done','plan':postplanpin,'validation_pipeline':vp,
          'steps':[{'name':n,'finished_at':'done','cleanup_verified':True} for n in ('audit','report','collect')]}
    postpin=write(postroot/'pipeline.json',post)
    plan={'schema':r.SCHEMA,'runner_sha256':r.sha(r.__file__),'execution':ep,'candidate_pins':pp,
          'driver':{'path':str(tmp_path/'control/validate_candidate_06.py'),'sha256':'d'*64},
          'validation_pipeline':vp,'postprocess_pipeline':postpin,'postprocess_plan':postplanpin,
          'native':native,'input_artifacts':inputs,'output':str(tmp_path/'temporary/supplemental-point017'),'timeout_seconds':7500}
    planpath=tmp_path/'control/supplemental-plan.json';planpin=write(planpath,plan)
    d=Driver();ctx={'plan':plan,'execution':e,'pins':{'source_sha256':'s'*64},'driver':d,'source':d.source,
        'output':Path(plan['output']),'receipt':tmp_path/'control/candidate06-supplemental-point017.json'}
    d.context=ctx
    return ctx,planpath,planpin['sha256']


def mutate_pin(plan,key,change):
    path=Path(plan[key]['path']);value=json.loads(path.read_text());change(value);plan[key]=write(path,value)


def test_terminal_scientific_failures_are_valid_diagnostic_context(fixture):
    c,_,_=fixture
    a,b=r.validate_terminal(c['plan'],c['execution'],c['pins'])
    assert a['status']==b['status']=='failed'


@pytest.mark.parametrize('change',['running','unclean','missing_step','wrong_native','wrong_source','wrong_pins','fake_resume',
    'post_running','post_unclean','post_missing_step','post_wrong_validation','post_wrong_source','post_wrong_output'])
def test_terminal_evidence_cannot_be_bypassed(fixture,change):
    c,_,_=fixture;p=c['plan']
    if change=='running':mutate_pin(p,'validation_pipeline',lambda v:v.update(status='running'))
    elif change=='unclean':mutate_pin(p,'validation_pipeline',lambda v:v.update(final_cleanup={'verified':False}))
    elif change=='missing_step':mutate_pin(p,'validation_pipeline',lambda v:v['steps'].pop())
    elif change=='wrong_native':mutate_pin(p,'validation_pipeline',lambda v:v['native'].update(sha256='x'*64))
    elif change=='wrong_source':mutate_pin(p,'validation_pipeline',lambda v:v['source'].update(sha256='x'*64))
    elif change=='wrong_pins':mutate_pin(p,'validation_pipeline',lambda v:v['required_pins'].update(sha256='x'*64))
    elif change=='fake_resume':mutate_pin(p,'validation_pipeline',lambda v:v['resume'].update(status='resumed'))
    elif change=='post_running':mutate_pin(p,'postprocess_pipeline',lambda v:v.update(status='running'))
    elif change=='post_unclean':mutate_pin(p,'postprocess_pipeline',lambda v:v['steps'][0].update(cleanup_verified=False))
    elif change=='post_missing_step':mutate_pin(p,'postprocess_pipeline',lambda v:v['steps'].pop())
    elif change=='post_wrong_validation':mutate_pin(p,'postprocess_pipeline',lambda v:v['validation_pipeline'].update(sha256='x'*64))
    elif change=='post_wrong_source':mutate_pin(p,'postprocess_plan',lambda v:v.update(source_sha256='x'*64))
    else:mutate_pin(p,'postprocess_plan',lambda v:v.update(output_root='/unrelated'))
    with pytest.raises(ValueError):r.validate_terminal(p,c['execution'],c['pins'])


@pytest.mark.parametrize('mode,code',[('strict',0),('floor',0),('failed',1),('missing',1)])
def test_run_preserves_classification_and_uses_owned_supervisor(fixture,mode,code):
    c,path,digest=fixture;d=c['driver'];d.mode=mode
    required_before=Path(c['plan']['validation_pipeline']['path']).read_bytes()
    post_before=Path(c['plan']['postprocess_pipeline']['path']).read_bytes()
    assert r.run(c,path,digest)==code
    result=json.loads(c['receipt'].read_text())
    assert result['final_cleanup']['verified'] and not result['required_gate_classifications_changed']
    assert result['covariance_authorized'] is False and result['campaign_resume']=='not_applicable'
    assert result.get('strict_nuisance_converged',False)==(mode=='strict')
    assert result.get('progress_only_floor_validated',False)==(mode=='floor')
    argv,kwargs=d.calls[0]
    assert kwargs['limit']==7500 and argv[argv.index('-c')+1]=='24'
    assert argv[-1]=='--allow-floor-limited' and kwargs['env']['OMP_NUM_THREADS']=='1'
    assert argv[argv.index('--source-profile')+1]==c['plan']['input_artifacts']['profile']['path']
    assert kwargs['env']['TMPDIR']==str(c['output']/'tmp')
    assert not d.owned.running and len(d.owned.calls)>=2
    assert Path(c['plan']['validation_pipeline']['path']).read_bytes()==required_before
    assert Path(c['plan']['postprocess_pipeline']['path']).read_bytes()==post_before
    with pytest.raises(ValueError,match='already exists'):r.run(c,path,digest)


@pytest.mark.parametrize('mode,error',[('timeout',subprocess.TimeoutExpired),('interrupt',KeyboardInterrupt),('wrong_source',ValueError)])
def test_failed_or_interrupted_work_is_cleaned_and_preserved(fixture,mode,error):
    c,path,digest=fixture;c['driver'].mode=mode
    with pytest.raises(error):r.run(c,path,digest)
    result=json.loads(c['receipt'].read_text())
    assert result['status']=='failed' and result['final_cleanup']['verified'] and result['finished_at']
    assert not c['driver'].owned.running


def test_cleanup_failure_cannot_claim_completed_or_clean(fixture):
    c,path,digest=fixture;c['driver'].mode='cleanup_failure'
    with pytest.raises(RuntimeError):r.run(c,path,digest)
    result=json.loads(c['receipt'].read_text())
    assert result['status']=='failed' and not result['final_cleanup']['verified']


def test_receipt_failure_after_launch_still_cleans_owned_child(fixture):
    c,path,digest=fixture;c['driver'].fail_save_at=2
    with pytest.raises(OSError):r.run(c,path,digest)
    assert not c['driver'].owned.running
    result=json.loads(c['receipt'].read_text());assert result['final_cleanup']['verified'] and result['status']=='failed'


@pytest.mark.parametrize('which',['plan','native','source','conflict','lock'])
def test_reject_before_launch_on_changed_state_or_competing_work(fixture,which):
    c,path,digest=fixture;held=None
    if which=='plan':path.write_text('{}')
    elif which=='native':Path(c['plan']['native']['path']).write_text('changed')
    elif which=='source':c['driver'].source={'sha256':'changed'}
    elif which=='conflict':c['driver'].mode='conflict'
    else:
        held=(Path(c['execution']['paths']['control'])/'candidate06-validation.lock').open('a')
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        with pytest.raises((ValueError,RuntimeError,BlockingIOError)):r.run(c,path,digest)
    finally:
        if held:held.close()
    assert not c['driver'].calls and not c['output'].exists() and not c['receipt'].exists()


def test_plan_change_during_run_fails_after_owned_cleanup(fixture):
    c,path,digest=fixture;c['driver'].after=lambda:path.write_text('{}')
    with pytest.raises(ValueError,match='during run'):r.run(c,path,digest)
    result=json.loads(c['receipt'].read_text());assert result['status']=='failed' and result['final_cleanup']['verified']


@pytest.mark.parametrize('change',['hash','schema','runner','timeout','unknown','execution'])
def test_load_context_rejects_unsealed_plan_before_import_or_execution(fixture,change):
    c,path,digest=fixture;p=c['plan']
    if change=='hash':digest='0'*64
    else:
        if change=='schema':p['schema']='unknown'
        elif change=='runner':p['runner_sha256']='0'*64
        elif change=='timeout':p['timeout_seconds']=7501
        elif change=='unknown':p['unexpected']=True
        else:p['execution']['sha256']='0'*64
        digest=write(path,p)['sha256']
    with pytest.raises(ValueError):r.load_context(path,digest)
    assert not c['output'].exists()


def full_plan(fixture):
    """An importable fake driver lets the complete loader's contract run."""
    c,path,_=fixture;p=c['plan'];e=c['execution']
    for role,pin in p['input_artifacts'].items():e['runtime_artifacts']['extra_point017_'+role]=pin
    profile=Path(p['input_artifacts']['profile']['path'])
    profile.write_text('<profile>'+''.join(p['input_artifacts'][role]['path'] for role in r.INPUT_ROLES[1:])+'</profile>')
    p['input_artifacts']['profile']=r.artifact(profile);e['runtime_artifacts']['extra_point017_profile']=p['input_artifacts']['profile']
    driver=Path(p['driver']['path'])
    driver.write_text('''import json
from pathlib import Path
def load_execution(path):return json.loads(Path(path).read_text())
def load_required_pins(path,execution):return json.loads(Path(path).read_text())
def verify_pins(pins,execution,path):return {'sha256':pins['source_sha256']}
''')
    p['driver']=r.artifact(driver)
    c['pins']['driver_sha256']=p['driver']['sha256']
    def seal():
        p['execution']=write(p['execution']['path'],e)
        c['pins']['execution_sha256']=p['execution']['sha256']
        p['candidate_pins']=write(p['candidate_pins']['path'],c['pins'])
        mutate_pin(p,'validation_pipeline',lambda v:v.update(required_pins=p['candidate_pins'],execution=p['execution']))
        mutate_pin(p,'postprocess_plan',lambda v:v.update(execution=p['execution'],candidate_pins=p['candidate_pins']))
        mutate_pin(p,'postprocess_pipeline',lambda v:v.update(plan=p['postprocess_plan'],validation_pipeline=p['validation_pipeline']))
        return write(path,p)['sha256']
    return c,path,seal


def test_complete_loader_accepts_exact_sealed_supplemental_identity(fixture):
    c,path,seal=full_plan(fixture)
    ctx=r.load_context(path,seal())
    assert ctx['output']==c['output'] and ctx['receipt']==c['receipt']
    assert ctx['source']=={'sha256':'s'*64}
    assert not c['output'].exists()


@pytest.mark.parametrize('change',['cpu','output','inputs_missing','swapped_input','xml_dependency','native','manifest','driver','native_path'])
def test_complete_loader_rejects_wrong_frozen_execution_or_inputs(fixture,change):
    c,path,seal=full_plan(fixture);p=c['plan'];e=c['execution']
    if change=='cpu':e['fit_cpu']=25
    elif change=='output':p['output']=str(c['output'].parent/'other')
    elif change=='inputs_missing':p['input_artifacts'].pop('density')
    elif change=='swapped_input':p['input_artifacts']['reference']=p['input_artifacts']['density']
    elif change=='xml_dependency':
        profile=Path(p['input_artifacts']['profile']['path']);profile.write_text('<wrong/>')
        p['input_artifacts']['profile']=r.artifact(profile);e['runtime_artifacts']['extra_point017_profile']=p['input_artifacts']['profile']
    elif change=='native':Path(p['native']['path']).write_text('changed native')
    elif change=='manifest':Path(p['native']['path']+'.build-manifest.json').write_text('{}')
    elif change=='driver':p['driver']['sha256']='0'*64
    else:p['native']['path']=str(Path(p['native']['path']).parent/'wrong-name')
    with pytest.raises(ValueError):r.load_context(path,seal())
    assert not c['output'].exists() and not c['receipt'].exists()
