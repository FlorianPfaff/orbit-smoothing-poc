#!/usr/bin/env python3
"""Non-native candidate09 namespace proof against frozen source, inputs and controls."""
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

def validate(execution_path,execution_sha,pins_path,pins_sha):
    require(sha(execution_path)==execution_sha,'Execution changed')
    require(sha(pins_path)==pins_sha,'Pins changed')
    pins=json.loads(Path(pins_path).read_text())
    require(pins.get('schema')=='orbit-poc-correctness-candidate09-pins-v1','Wrong candidate pin schema')
    require(pins.get('execution_sha256')==execution_sha,'Execution and pins attribution differs')
    driver_path=Path(pins_path).parent/'validate_candidate_09.py'
    require(sha(driver_path)==pins.get('driver_sha256'),'Driver changed')
    driver=load_module('recovery09_smoke_driver',driver_path)
    execution=driver.load_execution(execution_path)
    require(sha(sys.executable)==execution['runtime_artifacts']['control_python']['sha256'],'Use pinned control interpreter')
    checked_pins=driver.load_required_pins(pins_path,execution_path)
    require(checked_pins==pins,'Required pins differ')
    source=driver.verify_pins(pins,execution,execution_path)
    require(source['sha256']==pins['source_sha256'] and len(source['files'])==pins['source_file_count'],'Frozen source differs')
    return execution,pins,driver

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
assert files==f['files']
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
    for name in ('execution','pins','upstream-helper','upstream-reference','output'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('execution-sha256','pins-sha256'):p.add_argument('--'+name,required=True)
    a=p.parse_args();e,pins,d=validate(a.execution,a.execution_sha256,a.pins,a.pins_sha256)
    require(sha(a.upstream_helper)==UPSTREAM_HELPER_SHA and sha(a.upstream_reference)==UPSTREAM_REFERENCE_SHA,'Pinned upstream verifier changed')
    require(a.output.parent==Path(e['paths']['root'])/'staging','Smoke output must be a fresh staging child')
    with (Path(e['paths']['control'])/'candidate09-validation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        admission=d.admission(e);changed=derive(e,a.output);ep=a.output/'execution.json';ep.write_text(json.dumps(changed,indent=2)+'\n')
        d.load_execution(ep)
        code=a.output/'inside.py';code.write_text(INSIDE);logpath=a.output/'stdout.log'
        source_freeze=str(d.host_path(pins['new_source_freeze']['path'],e))
        command=[e['runtime_artifacts']['control_python']['path'],e['paths']['wrapper'],'--execution',str(ep),'--execution-sha256',sha(ep),'--',e['paths']['python'],str(code),str(ep),source_freeze,str(a.upstream_helper),str(a.upstream_reference),UPSTREAM_HELPER_SHA,UPSTREAM_REFERENCE_SHA]
        status,cleanup,failure=run_owned(d,command,e['paths']['root'],dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),logpath)
        result=None
        if failure is None:
            try:
                require(status==0,'Namespace smoke failed: '+logpath.read_text())
                require(cleanup.get('verified') is True,'Namespace cleanup did not verify')
                result=json.loads(logpath.read_text());require_fresh(e)
                require(sha(a.execution)==a.execution_sha256 and sha(a.pins)==a.pins_sha256,'Pinned controls changed during smoke')
                require(result['source_sha256']==pins['source_sha256'] and result['source_files']==pins['source_file_count'],'Wrong source inside namespace')
            except BaseException as error:failure=repr(error)
        receipt={'schema':'orbit-poc-recovery09-namespace-smoke-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':failure is None and status==0 and cleanup.get('verified') is True,'error':failure,'helper':artifact(__file__),'execution':artifact(a.execution),'pins':artifact(a.pins),'smoke_execution':artifact(ep),'wrapper':artifact(e['paths']['wrapper']),'upstream_helper':artifact(a.upstream_helper),'upstream_reference':artifact(a.upstream_reference),'argv':command,'returncode':status,'cleanup':cleanup,'admission':admission,'production_mutable_directories_absent':all(not Path(e['paths'][k]).exists() and not Path(e['paths'][k]).is_symlink() for k in MUTABLE),'scientific_validation_complete':False,'scope':'Read-only scientific imports, source/runtime identities and complete pinned upstream tree; no native fit or compiler.'}
        if result is not None:receipt['result']=result
        with (a.output/'receipt.json').open('x') as stream:json.dump(receipt,stream,sort_keys=True,indent=2);stream.write('\n')
        require(receipt['passed'],'Namespace smoke did not verify');print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
