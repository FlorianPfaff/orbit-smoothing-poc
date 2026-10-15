#!/usr/bin/env python3
"""Fresh, diagnostic-only native build and exact off/on failure replay."""
import argparse, fcntl, hashlib, importlib.util, json, os, shutil, signal
from pathlib import Path

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def require(ok,why):
    if not ok:raise RuntimeError(why)
def checked(pin):
    require(set(pin)=={'path','sha256'} and Path(pin['path']).is_absolute(),'Invalid pin')
    require(sha(pin['path'])==pin['sha256'],'Pin changed: '+pin['path'])
def artifact(p):return {'path':str(p),'sha256':sha(p)}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--sha256',required=True);args=parser.parse_args()
    require(sha(args.plan)==args.sha256,'Plan changed')
    plan=json.loads(args.plan.read_text())
    require(set(plan)=={'schema','runner','execution','driver','source_freeze','helpers','inputs','input_links','prior_pipeline','last_generation'},'Unknown plan fields')
    require(plan['schema']=='orbit-poc-diagnostic-row-trace-plan-v1' and plan['last_generation']==8,'Invalid diagnostic scope')
    for key in ('runner','execution','driver','source_freeze','prior_pipeline'):checked(plan[key])
    require(plan['runner']['sha256']==sha(__file__),'Runner mismatch')
    for pin in (*plan['helpers'].values(),*plan['inputs'].values()):checked(pin)
    spec=importlib.util.spec_from_file_location('owned06',plan['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    e=d.load_execution(plan['execution']['path']);paths={k:Path(v) for k,v in e['paths'].items()};run=paths['run'];registry=[];journal={};handlers={}
    frozen=json.loads(Path(plan['source_freeze']['path']).read_text())['source']
    def guard():
        require(sha(args.plan)==args.sha256,'Plan mutated')
        for key in ('runner','execution','driver','source_freeze','prior_pipeline'):checked(plan[key])
        for pin in (*plan['helpers'].values(),*plan['inputs'].values()):checked(pin)
        for link,target in plan['input_links'].items():
            require(Path(link).is_symlink() and str(Path(link).readlink())==target,'Input link changed: '+link)
        require(d.source_receipt(paths['source'])==frozen,'Frozen source changed')
        for pin in e['runtime_artifacts'].values():require(sha(d.resolved_host_path(pin['path'],e))==pin['sha256'],'Runtime changed: '+pin['path'])
        d.admission(e,registry)
    require(not run.exists(),'Diagnostic output exists; no implicit retry')
    prior=json.loads(Path(plan['prior_pipeline']['path']).read_text());require(prior['status']=='failed' and prior['final_cleanup']['verified'],'Original attempt must be terminal and clean')
    with (paths['control']/'diagnostic.lock').open('a') as lock, (Path(plan['prior_pipeline']['path']).parents[1]/'control/candidate06-validation.lock').open('a') as global_lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(global_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        guard()
        for key in ('native_source','build','binaries','run','temporary'):require(not paths[key].exists(),'Fresh directory required: '+key)
        for key in ('native_source','build','binaries','run','temporary'):paths[key].mkdir()
        journal={'schema':'orbit-poc-diagnostic-row-trace-run-v1','status':'running','started_at':d.stamp(),'plan':artifact(args.plan),'admission':d.admission(e),'steps':[],'scope':'Diagnostic only, no acceptance gate substitution or covariance authorization','scientific_correctness_resolved':False}
        def save():d.save(run/'pipeline.json',journal)
        def command(name,cmd,timeout,allowed=(0,)):
            guard();entry={'name':name,'started_at':d.stamp(),'status':'running','command':list(map(str,cmd))};journal['steps'].append(entry)
            actual=[e['runtime_artifacts']['control_python']['path'],paths['wrapper'],'--execution',plan['execution']['path'],'--execution-sha256',plan['execution']['sha256'],'--',*cmd]
            env=dict(os.environ,PYTHONPATH=str(paths['source']/'src'),PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',TMPDIR=str(paths['temporary']))
            env.pop('ORBIT_POC_ROW_TRACE_DIRECTORY',None)
            def started(pid):entry['pid']=pid;save()
            def finished(value):entry.update(value);save()
            try:
                save()
                with (run/(name+'.log')).open('x') as log:
                    code=d.supervise(actual,cwd=paths['source'],env=env,log=log,limit=timeout,guard_live=lambda:d.admission(e,registry),on_started=started,on_finished=finished,registry=registry)
            except BaseException as error:
                entry.update(status='interrupted_timeout_or_supervision_failure',error=type(error).__name__+': '+str(error),finished_at=d.stamp())
                save()
                raise
            entry.update(returncode=code,status='completed' if code in allowed else 'failed',finished_at=d.stamp());save();guard();require(code in allowed,name+' failed')
        try:
            for number in (signal.SIGINT,signal.SIGTERM):handlers[number]=signal.getsignal(number);signal.signal(number,d.interrupted)
            save()
            command('clone',['git','clone','--no-hardlinks','--no-checkout',paths['upstream_repository'],paths['native_source']],600)
            command('checkout',['git','-C',paths['native_source'],'checkout','--detach','7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee'],600)
            command('build',['/usr/bin/taskset','-c','24,25,26,27',paths['python'],plan['helpers']['build']['path'],'--source-dir',paths['native_source'],'--build-dir',paths['build'],'--prefix',paths['prefix'],'--cmake-executable',paths['cmake'],'--numerics','--jobs','4'],7200)
            native=paths['binaries']/('groops-'+sha(paths['build']/'groops')[:16]);shutil.copy2(paths['build']/'groops',native);native.chmod(0o555);shutil.copy2(paths['build']/'build-manifest.json',str(native)+'.build-manifest.json');journal['native']=artifact(native);save()
            for name in ('trace-off','trace-on'):
                native_env=['env','ORBIT_POC_CORRECTNESS_NATIVE='+str(native),'ORBIT_POC_V31_NATIVE='+str(native),'ORBIT_POC_GROOPS='+str(native)]
                if name=='trace-on':
                    (run/'trace').mkdir();native_env+=['ORBIT_POC_ROW_TRACE_DIRECTORY='+str(run/'trace')]
                command(name,['/usr/bin/taskset','-c','24',*native_env,paths['python'],paths['source']/'scripts/validate_numerics_nuisance.py','--source-profile',plan['inputs']['profile']['path'],'--native',native,'--output',run/name],7500,allowed=(0,1))
                checked(journal['native'])
            command('equivalence',[paths['python'],plan['helpers']['compare']['path'],'--reference',Path(plan['inputs']['profile']['path']).parent,'--trace-off',run/'trace-off','--trace-on',run/'trace-on','--last-generation','8','--receipt',run/'equivalence.json'],600)
            journal['status']='completed';save()
        except BaseException as error:
            journal.update(status='failed',error=type(error).__name__+': '+str(error));raise
        finally:
            with d.cleanup_signals():
                errors=[]
                for owned in registry:
                    try:owned.cleanup(force=owned.child.poll() is None)
                    except BaseException as error:errors.append(type(error).__name__+': '+str(error))
                journal['final_cleanup']={'verified':not errors,'errors':errors,'commands':[v.last_cleanup for v in registry]};journal['finished_at']=d.stamp()
                if errors:journal['status']='failed'
                try:save()
                finally:
                    for number,handler in handlers.items():signal.signal(number,handler)
    print(json.dumps({'status':journal['status'],'pipeline':str(run/'pipeline.json')}))
if __name__=='__main__':main()
