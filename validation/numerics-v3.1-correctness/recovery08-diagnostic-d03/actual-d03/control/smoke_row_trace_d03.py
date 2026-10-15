#!/usr/bin/env python3
"""Non-native D03 namespace proof after the original validation is terminal."""
import argparse, copy, datetime, fcntl, hashlib, importlib.util, json, os, signal, sys, time
from pathlib import Path

MUTABLE=('native_source','build','binaries','run','temporary')
UPSTREAM_HELPER_SHA='cbdcd6e19abee3ec3df8beb62147138ea6a9237a8cf0617b1c78140efbf1261c'
UPSTREAM_REFERENCE_SHA='3f5477e2482f108ff567ccde6e57d50bd050e7dc71eba5688e4839680cf61cdf'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def artifact(path):return {'path':str(path),'sha256':sha(path)}
def require(ok,why):
    if not ok:raise RuntimeError(why)
def checked(pin):
    require(set(pin)=={'path','sha256'} and Path(pin['path']).is_absolute(),'Invalid artifact pin')
    require(sha(pin['path'])==pin['sha256'],'Artifact changed: '+pin['path'])
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def validate(execution_path,execution_sha,plan_path,plan_sha):
    require(sha(execution_path)==execution_sha,'Execution changed')
    require(sha(plan_path)==plan_sha,'Plan changed')
    plan=json.loads(Path(plan_path).read_text())
    require(set(plan)=={'schema','runner','execution','driver','source_freeze','helpers','inputs','input_links','prior_pipeline','prior_postprocess','last_generation'},'Unknown plan fields')
    require(plan['schema']=='orbit-poc-diagnostic-row-trace-plan-v2' and plan['last_generation']==4,'Wrong diagnostic plan')
    require(plan['execution']=={'path':str(execution_path),'sha256':execution_sha},'Plan execution attribution differs')
    for key in ('runner','execution','driver','source_freeze','prior_pipeline','prior_postprocess'):checked(plan[key])
    for pin in (*plan['helpers'].values(),*plan['inputs'].values()):checked(pin)
    prior=json.loads(Path(plan['prior_pipeline']['path']).read_text());post=json.loads(Path(plan['prior_postprocess']['path']).read_text())
    require(prior.get('status')=='failed' and prior.get('finished_at') and prior.get('final_cleanup',{}).get('verified') is True,'Original validation is not terminal, failed and clean')
    require(post.get('status') in ('completed','failed') and post.get('finished_at') and post.get('steps') and all(s.get('cleanup_verified') is True for s in post['steps']),'Original postprocessor is not terminal and clean')
    require(post.get('validation_pipeline',{}).get('sha256')==plan['prior_pipeline']['sha256'],'Postprocessor attribution differs')
    driver=load_module('d03_smoke_owned_driver',plan['driver']['path']);execution=driver.load_execution(execution_path)
    require(artifact(execution['paths']['wrapper'])==plan['helpers']['wrapper'],'Wrapper identity differs')
    require(sha(sys.executable)==execution['runtime_artifacts']['control_python']['sha256'],'Use the pinned control interpreter')
    for pin in execution['runtime_artifacts'].values():require(sha(driver.resolved_host_path(pin['path'],execution))==pin['sha256'],'Runtime changed: '+pin['path'])
    frozen=json.loads(Path(plan['source_freeze']['path']).read_text())['source']
    require(len(frozen['files'])==771 and frozen['sha256']=='774d6d777e1f5caf09b5599a8b469e421327f2e1f962eb75a5af17b0bc8bf8c2','Wrong candidate source')
    require(driver.source_receipt(execution['paths']['source'])==frozen,'Source inventory changed')
    inputs=load_module('d03_smoke_input_identity',plan['helpers']['prepare']['path'])
    actual,links,identity=inputs.collect_inputs(Path(plan['inputs']['profile']['path']),execution,driver)
    require(actual==plan['inputs'] and links==plan['input_links'],'Original XML input closure changed')
    require(identity==json.loads(Path(plan['helpers']['input_identity']['path']).read_text()),'Original XML input identities changed')
    for link,target in links.items():require(Path(link).is_symlink() and str(Path(link).readlink())==target,'Original input link changed')
    return execution,plan,driver

def require_fresh(execution):
    for name in MUTABLE:
        path=Path(execution['paths'][name]);require(not path.exists() and not path.is_symlink(),'Production output is not absent: '+name)

def derive(execution,smoke):
    require_fresh(execution);smoke=Path(smoke)
    root=Path(execution['paths']['root']);require(smoke.parent==root/'staging' and not smoke.exists() and not smoke.is_symlink(),'Fresh immediate staging child required')
    smoke.mkdir(parents=True)
    changed=copy.deepcopy(execution)
    for name in MUTABLE:
        path=smoke/name;path.mkdir();changed['paths'][name]=str(path)
    require({k for k in execution if execution[k]!=changed[k]}=={'paths'},'Non-path execution mutation')
    require({k for k in execution['paths'] if execution['paths'][k]!=changed['paths'][k]}==set(MUTABLE),'Unexpected execution path mutation')
    return changed

INSIDE=r'''
from pathlib import Path
import ctypes,hashlib,json,os,sys,platform,importlib.util
import numpy,scipy,gtsam
c=json.loads(Path(sys.argv[1]).read_bytes());f=json.loads(Path(sys.argv[2]).read_bytes())['source'];source=Path(c['paths']['source'])
assert os.statvfs(source).f_flag & os.ST_RDONLY
files={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.rglob('*')) if p.is_file()}
assert files==f['files'] and len(files)==771
libraries={}
for name,item in c['runtime_artifacts'].items():
 if name.startswith('glibc239_'):
  actual=hashlib.sha256(Path(item['path']).read_bytes()).hexdigest();assert actual==item['sha256'];libraries[name]=actual
assert libraries
libc=ctypes.CDLL(None);libc.gnu_get_libc_version.restype=ctypes.c_char_p;version=libc.gnu_get_libc_version().decode();assert version=='2.39'
for key in ('native_source','build','binaries','run','temporary'):
 path=Path(c['paths'][key]);assert not (os.statvfs(path).f_flag & os.ST_RDONLY)
 (path/'namespace-writable-probe.txt').write_text('Only this staging path is intentionally writable.\n')
helper=Path(sys.argv[3]);reference=Path(sys.argv[4])
assert hashlib.sha256(helper.read_bytes()).hexdigest()==sys.argv[5]
assert hashlib.sha256(reference.read_bytes()).hexdigest()==sys.argv[6]
spec=importlib.util.spec_from_file_location('upstream_check',helper);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
upstream=module.check(c['paths']['upstream_repository'],json.loads(reference.read_bytes()))
assert os.statvfs(c['paths']['upstream_repository']).f_flag & os.ST_RDONLY
print(json.dumps({'upstream':upstream,'source_read_only':True,'upstream_read_only':True,'source_files':len(files),'source_sha256':f['sha256'],'glibc':version,'canonical_library_hashes':libraries,'scientific_imports':['numpy','scipy','gtsam'],'python':platform.python_version(),'numpy':numpy.__version__,'scipy':scipy.__version__,'writable_outputs':'five staging-only paths','pid_namespace':os.readlink('/proc/self/ns/pid')}))
'''

def run_owned(driver,command,cwd,env,logpath,limit=120):
    owned=None;status=None;failure=None;handlers={};cleanup={'verified':False}
    try:
        for number in (signal.SIGINT,signal.SIGTERM):
            handlers[number]=signal.getsignal(number);signal.signal(number,driver.interrupted)
        with Path(logpath).open('x') as log:
            owned=driver.OwnedCommand(command,cwd=cwd,env=env,log=log)
            deadline=time.monotonic()+limit
            while owned.child.poll() is None:
                owned.observe()
                if time.monotonic()>deadline:raise TimeoutError('Finite namespace smoke timed out')
                time.sleep(.05)
            status=owned.child.returncode
    except BaseException as error:
        failure=repr(error)
    finally:
        try:
            with driver.cleanup_signals():
                if owned is not None:cleanup=owned.cleanup(force=owned.child.poll() is None)
        except BaseException as error:
            cleanup={'verified':False,'error':repr(error)}
            failure=(failure+'; ' if failure else '')+'cleanup: '+repr(error)
        finally:
            for number,handler in handlers.items():signal.signal(number,handler)
    return status,cleanup,failure

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('execution','plan','upstream-helper','upstream-reference','output'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('execution-sha256','plan-sha256'):p.add_argument('--'+name,required=True)
    a=p.parse_args();e,plan,d=validate(a.execution,a.execution_sha256,a.plan,a.plan_sha256)
    require(sha(a.upstream_helper)==UPSTREAM_HELPER_SHA and sha(a.upstream_reference)==UPSTREAM_REFERENCE_SHA,'Pinned upstream verifier changed')
    require(a.output.parent==Path(e['paths']['root'])/'staging','Smoke output must be a fresh staging child')
    with (Path(e['paths']['control'])/'diagnostic.lock').open('a') as lock, (Path(plan['prior_pipeline']['path']).parents[1]/'control/candidate07-validation.lock').open('a') as global_lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(global_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        admission=d.admission(e);changed=derive(e,a.output);ep=a.output/'execution.json';ep.write_text(json.dumps(changed,indent=2)+'\n')
        d.load_execution(ep)
        code=a.output/'inside.py';code.write_text(INSIDE);logpath=a.output/'stdout.log'
        command=[e['runtime_artifacts']['control_python']['path'],e['paths']['wrapper'],'--execution',str(ep),'--execution-sha256',sha(ep),'--',e['paths']['python'],str(code),str(ep),plan['source_freeze']['path'],str(a.upstream_helper),str(a.upstream_reference),UPSTREAM_HELPER_SHA,UPSTREAM_REFERENCE_SHA]
        status,cleanup,failure=run_owned(d,command,e['paths']['root'],dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),logpath)
        result=None
        if failure is None:
            try:
                require(status==0,'Namespace smoke failed: '+logpath.read_text())
                require(cleanup.get('verified') is True,'Namespace cleanup did not verify')
                result=json.loads(logpath.read_text());require_fresh(e)
                require(sha(a.execution)==a.execution_sha256 and sha(a.plan)==a.plan_sha256,'Pinned controls changed during smoke')
            except BaseException as error:failure=repr(error)
        receipt={'schema':'orbit-poc-d03-namespace-smoke-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':failure is None and status==0 and cleanup.get('verified') is True,'error':failure,'helper':artifact(__file__),'execution':artifact(a.execution),'plan':artifact(a.plan),'smoke_execution':artifact(ep),'wrapper':artifact(e['paths']['wrapper']),'upstream_helper':artifact(a.upstream_helper),'upstream_reference':artifact(a.upstream_reference),'argv':command,'returncode':status,'cleanup':cleanup,'admission':admission,'production_mutable_directories_absent':all(not Path(e['paths'][k]).exists() and not Path(e['paths'][k]).is_symlink() for k in MUTABLE),'scientific_validation_complete':False,'scope':'Read-only scientific imports, source/runtime identities and complete pinned upstream tree; no native fit or compiler.'}
        if result is not None:receipt['result']=result
        with (a.output/'receipt.json').open('x') as stream:json.dump(receipt,stream,sort_keys=True,indent=2);stream.write('\n')
        require(receipt['passed'],'Namespace cleanup did not verify');print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
